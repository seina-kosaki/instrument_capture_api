import { useEffect, useState, type FormEvent, type MouseEvent } from "react";
import {
  Activity,
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Camera,
  Check,
  CheckCircle2,
  Circle,
  Crosshair,
  ImagePlus,
  Layers3,
  Plus,
  Power,
  RotateCcw,
  Search,
  Send,
  Square,
  Trash2,
  X,
} from "lucide-react";
import {
  API_BASE,
  ApiError,
  apiRequest,
  imageUrl,
  type CameraStatus,
  type Declaration,
  type Hint,
  type ImageRecord,
  type Instrument,
  type Point,
  type Session,
  type TagResult,
} from "./api";
import AnalysisView from "./AnalysisView";

type Step = "session" | "declaration" | "confirm" | "capture";
type CaptureMode = "imaging" | "tagging";
type PointKind = "center" | "end_a" | "end_b";

const STEPS: Array<{ id: Step; label: string }> = [
  { id: "session", label: "セッション" },
  { id: "declaration", label: "器具の宣言" },
  { id: "confirm", label: "配置確認" },
  { id: "capture", label: "撮影・タグ付け" },
];

const EMPTY_CAMERA: CameraStatus = { state: "closed", error: null, camera_name: "unknown" };

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.issues.length > 0) {
    return `${error.message}: ${error.issues.map((issue) => issue.message).join(" / ")}`;
  }
  return error instanceof Error ? error.message : "処理に失敗しました";
}

function App() {
  const [workspaceView, setWorkspaceView] = useState<"capture" | "analysis">("capture");
  const [step, setStep] = useState<Step>("session");
  const [session, setSession] = useState<Session | null>(null);
  const [declaration, setDeclaration] = useState<Declaration | null>(null);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [instrumentByUid, setInstrumentByUid] = useState<Record<string, Instrument>>({});
  const [searchText, setSearchText] = useState("");
  const [selected, setSelected] = useState<Record<string, true>>({});
  const [operator, setOperator] = useState("");
  const [location, setLocation] = useState("");
  const [camera, setCamera] = useState<CameraStatus>(EMPTY_CAMERA);
  const [captureMode, setCaptureMode] = useState<CaptureMode>("imaging");
  const [previewTick, setPreviewTick] = useState(0);
  const [image, setImage] = useState<ImageRecord | null>(null);
  const [recentImages, setRecentImages] = useState<ImageRecord[]>([]);
  const [hints, setHints] = useState<Hint[]>([]);
  const [selectedHintIndex, setSelectedHintIndex] = useState<number | null>(null);
  const [selectedUid, setSelectedUid] = useState("");
  const [pointKind, setPointKind] = useState<PointKind>("center");
  const [taggedBy, setTaggedBy] = useState("");
  const [validation, setValidation] = useState<TagResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => {
      apiRequest<Instrument[]>(`/instruments?q=${encodeURIComponent(searchText)}&limit=100`)
        .then((result) => {
          setInstruments(result);
          setInstrumentByUid((current) => ({
            ...current,
            ...Object.fromEntries(result.map((instrument) => [instrument.instrument_uid, instrument])),
          }));
        })
        .catch((cause: unknown) => setError(errorMessage(cause)));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [searchText]);

  useEffect(() => {
    if (step !== "capture" || captureMode !== "imaging" || camera.state !== "ready") return;
    const timer = window.setInterval(() => setPreviewTick((tick) => tick + 1), 180);
    return () => window.clearInterval(timer);
  }, [step, captureMode, camera.state]);

  async function run<T>(operation: () => Promise<T>, onSuccess: (result: T) => void) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      onSuccess(await operation());
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  function startSession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run(
      () => apiRequest<Session>("/sessions", {
        method: "POST",
        body: JSON.stringify({ operator, location }),
      }),
      (created) => {
        setSession(created);
        setSelected({});
        setDeclaration(null);
        setRecentImages([]);
        setImage(null);
        setHints([]);
        setStep("declaration");
      },
    );
  }

  function toggleInstrument(uid: string) {
    setSelected((current) => {
      const next = { ...current };
      if (next[uid]) delete next[uid];
      else next[uid] = true;
      return next;
    });
  }

  function createDeclaration() {
    if (!session) return;
    const items = Object.keys(selected).map((instrument_uid) => ({ instrument_uid }));
    void run(
      () => apiRequest<Declaration>(`/sessions/${session.session_id}/declarations`, {
        method: "POST",
        body: JSON.stringify({ items }),
      }),
      (created) => {
        setDeclaration(created);
        setStep("confirm");
      },
    );
  }

  function confirmArrangement() {
    if (!declaration) return;
    void run(
      async () => {
        const confirmed = await apiRequest<Declaration>(`/declarations/${declaration.declaration_id}/confirm`, { method: "POST" });
        const cameraStatus = await apiRequest<CameraStatus>("/camera/open", { method: "POST" });
        return { confirmed, cameraStatus };
      },
      ({ confirmed, cameraStatus }) => {
        setDeclaration(confirmed);
        setCamera(cameraStatus);
        setStep("capture");
      },
    );
  }

  function connectCamera() {
    void run(
      () => apiRequest<CameraStatus>("/camera/open", { method: "POST" }),
      setCamera,
    );
  }

  function captureImage() {
    if (!declaration) return;
    void run(
      () => apiRequest<ImageRecord>(`/declarations/${declaration.declaration_id}/capture`, { method: "POST" }),
      (captured) => {
        setImage(captured);
        setRecentImages((current) => [captured, ...current]);
        setHints([]);
        setSelectedHintIndex(null);
        setValidation(null);
        setPointKind("center");
        setSelectedUid(declaration.items[0]?.instrument_uid ?? "");
        setCaptureMode("tagging");
        setNotice("撮影画像を保存しました。対象器具を選び、画像上に点を登録してください。");
      },
    );
  }

  function addPoint(event: MouseEvent<HTMLDivElement>) {
    if (!image || !selectedUid) return;
    const activeIndex = selectedHintIndex !== null && hints[selectedHintIndex]?.instrument_uid === selectedUid
      ? selectedHintIndex
      : null;
    const targetIndex = activeIndex ?? (pointKind === "center" ? -1 : hints.reduce(
      (lastIndex, hint, hintIndex) => hint.instrument_uid === selectedUid && hint.center ? hintIndex : lastIndex,
      -1,
    ));
    if (pointKind !== "center" && (targetIndex < 0 || !hints[targetIndex]?.center)) {
      setError("先に中心点を登録してください。");
      return;
    }
    const bounds = event.currentTarget.getBoundingClientRect();
    const point: Point = {
      x: Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width)),
      y: Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height)),
      status: "visible",
    };
    if (pointKind === "center" && targetIndex < 0) {
      setHints((current) => [...current, {
          instrument_uid: selectedUid,
          hint_source: "manual",
          visible: true,
          center: point,
          end_a: null,
          end_b: null,
          occluded: false,
          added_after_capture: false,
        }]);
      setSelectedHintIndex(hints.length);
    } else {
      setHints((current) => current.map((hint, hintIndex) => {
        if (hintIndex !== targetIndex) return hint;
        if (pointKind === "center") return { ...hint, center: point, visible: true, hint_source: "manual" };
        return { ...hint, [pointKind]: point };
      }));
      setSelectedHintIndex(targetIndex);
    }
    setValidation(null);
    setError("");
  }

  function selectInstrument(uid: string) {
    setSelectedUid(uid);
    setSelectedHintIndex(null);
  }

  function reassignSelectedHint(uid: string) {
    setSelectedUid(uid);
    if (selectedHintIndex === null) return;
    setHints((current) => current.map((hint, index) => index === selectedHintIndex
      ? { ...hint, instrument_uid: uid }
      : hint));
    setValidation(null);
  }

  function removeHint(index: number) {
    setHints((current) => current.filter((_, hintIndex) => hintIndex !== index));
    setSelectedHintIndex((current) => {
      if (current === null || current === index) return null;
      return current > index ? current - 1 : current;
    });
    setValidation(null);
  }

  function selectImageForTagging(record: ImageRecord) {
    void run(
      () => apiRequest<TagResult>(`/images/${record.image_id}/tags`),
      (result) => {
        setImage(record);
        setHints(result.hints.map(({ instrument_uid, hint_source, visible, center, end_a, end_b, occluded, added_after_capture }) => ({
          instrument_uid, hint_source, visible, center, end_a, end_b, occluded, added_after_capture,
        })));
        setSelectedHintIndex(null);
        setSelectedUid(result.hints[0]?.instrument_uid ?? declaration?.items[0]?.instrument_uid ?? "");
        setValidation(null);
        setCaptureMode("tagging");
      },
    );
  }

  function validateTags() {
    if (!image) return;
    void run(
      () => apiRequest<TagResult>(`/images/${image.image_id}/tags/validate`, {
        method: "POST",
        body: JSON.stringify({ hints, tagged_by: taggedBy }),
      }),
      (result) => {
        setValidation(result);
        if (result.errors.length === 0) setNotice("検証が完了しました。問題がなければ保存できます。");
      },
    );
  }

  function saveTags() {
    if (!image) return;
    void run(
      () => apiRequest<TagResult>(`/images/${image.image_id}/tags`, {
        method: "PUT",
        body: JSON.stringify({ hints, tagged_by: taggedBy }),
      }),
      (result) => {
        setValidation(result);
        setImage((current) => current ? { ...current, tag_status: "tagged" } : current);
        setRecentImages((current) => current.map((record) => record.image_id === image.image_id
          ? { ...record, tag_status: "tagged" }
          : record));
        setNotice("タグを保存しました。");
      },
    );
  }

  function rearrange() {
    if (!declaration) return;
    void run(
      () => apiRequest<Declaration>(`/declarations/${declaration.declaration_id}/rearrange`, { method: "POST" }),
      (updated) => {
        setDeclaration(updated);
        setImage(null);
        setSelectedHintIndex(null);
        setHints([]);
        setValidation(null);
        setNotice(`配置 ${updated.arrangement_no} に更新しました。`);
      },
    );
  }

  function closeSession() {
    if (!session) return;
    void run(
      async () => {
        await apiRequest<CameraStatus>("/camera/close", { method: "POST" });
        return apiRequest<Session>(`/sessions/${session.session_id}/close`, { method: "POST" });
      },
      () => {
        setCamera(EMPTY_CAMERA);
        setStep("session");
        setSession(null);
        setDeclaration(null);
        setImage(null);
        setRecentImages([]);
        setSelectedHintIndex(null);
        setNotice("セッションを終了しました。");
      },
    );
  }

  function goBack() {
    if (step === "confirm") setStep("declaration");
    if (step === "declaration") {
      setStep("session");
      setSession(null);
    }
  }

  const declaredTypeCount = Object.keys(selected).length;
  const pointLabels: Record<PointKind, string> = { center: "中心", end_a: "端点 A", end_b: "端点 B" };
  const previewUrl = `${API_BASE}/camera/preview?frame=${previewTick}`;

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="器具撮影ホーム">
          <span className="brand-mark"><Crosshair size={19} strokeWidth={2.2} /></span>
          <span><strong>FIELDNOTE</strong><small>INSTRUMENT CAPTURE</small></span>
        </a>
        <div className="topbar-meta">
          <span className={`connection ${camera.state === "ready" ? "is-ready" : ""}`}>
            <span className="connection-dot" />
            {camera.state === "ready" ? "CAMLIB 接続中" : "CAMLIB 未接続"}
          </span>
          <span className="api-address"><Activity size={14} /> API {API_BASE.replace(/^https?:\/\//, "")}</span>
        </div>
      </header>

      <div className="workspace" id="top">
        <aside className="rail">
          <div className="rail-heading">撮影フロー</div>
          <nav className="step-list" aria-label="撮影ステップ">
            {STEPS.map((item, index) => {
              const currentIndex = STEPS.findIndex((entry) => entry.id === step);
              const complete = index < currentIndex;
              const active = item.id === step;
              return (
                <div className={`step-item ${active ? "active" : ""} ${complete ? "complete" : ""}`} key={item.id}>
                  <span className="step-icon">{complete ? <Check size={15} /> : <span>{String(index + 1).padStart(2, "0")}</span>}</span>
                  <span>{item.label}</span>
                </div>
              );
            })}
          </nav>

          <div className="rail-session">
            <span className="eyebrow">CURRENT SESSION</span>
            <strong>{session ? session.operator || "撮影者未入力" : "セッション未開始"}</strong>
            <span>{session?.location || "撮影場所"}</span>
            {declaration && <span className="rail-arrangement">配置 {declaration.arrangement_no}</span>}
          </div>
          <div className="rail-bottom"><span className="rail-dot" /> ローカルカメラステーション</div>
        </aside>

        <main className="main-content">
          <div className="page-heading">
            <div>
              <span className="eyebrow">SURGICAL INSTRUMENT DATA</span>
              <h1>{workspaceView === "analysis" ? "取得データ解析" : step === "session" ? "撮影セッション" : step === "declaration" ? "撮影対象を準備" : step === "confirm" ? "器具の配置を確認" : "撮影とタグ付け"}</h1>
            </div>
            <div className="page-heading-actions">
              <div className="workspace-switch" role="tablist" aria-label="作業ビュー">
                <button role="tab" aria-selected={workspaceView === "capture"} className={workspaceView === "capture" ? "selected" : ""} onClick={() => setWorkspaceView("capture")}><Camera size={15} /> 撮影</button>
                <button role="tab" aria-selected={workspaceView === "analysis"} className={workspaceView === "analysis" ? "selected" : ""} onClick={() => setWorkspaceView("analysis")}><Activity size={15} /> 解析</button>
              </div>
              {session && <button className="button button-quiet" onClick={closeSession} disabled={busy} title="セッション終了"><Power size={16} /> 終了</button>}
            </div>
          </div>

          {error && <div className="alert alert-error" role="alert"><AlertCircle size={18} /><span>{error}</span><button onClick={() => setError("")} aria-label="エラーを閉じる"><X size={16} /></button></div>}
          {notice && <div className="alert alert-success" role="status"><CheckCircle2 size={18} /><span>{notice}</span><button onClick={() => setNotice("")} aria-label="通知を閉じる"><X size={16} /></button></div>}

          {workspaceView === "analysis" ? <AnalysisView /> : <>
          {step === "session" && (
            <section className="session-layout">
              <div className="intro-band">
                <div className="intro-index">01 <span>/ SESSION</span></div>
                <h2>記録条件を登録して<br />撮影を開始します。</h2>
                <p>撮影条件は画像メタデータとセッション記録に紐づきます。</p>
                <div className="intro-rule" />
                <div className="intro-detail"><span>CAMERA SOURCE</span><strong>camlib · camera_id.yaml</strong></div>
              </div>
              <form className="form-panel" onSubmit={startSession}>
                <div className="section-kicker">SESSION DETAILS <span>必須項目を入力</span></div>
                <label className="field-label" htmlFor="operator">撮影者</label>
                <input id="operator" value={operator} onChange={(event) => setOperator(event.target.value)} placeholder="氏名または識別子" />
                <label className="field-label" htmlFor="location">撮影場所</label>
                <input id="location" value={location} onChange={(event) => setLocation(event.target.value)} placeholder="例：器材準備室" />
                <div className="form-note"><Circle size={9} fill="currentColor" /> カメラは撮影PCに接続されたcamlibデバイスを使用します。</div>
                <button className="button button-primary button-wide" type="submit" disabled={busy}>
                  セッションを開始 <ArrowRight size={17} />
                </button>
              </form>
            </section>
          )}

          {step === "declaration" && (
            <section className="declaration-layout">
              <div className="catalog-pane">
                <div className="section-heading"><div><span className="eyebrow">INSTRUMENT CATALOG</span><h2>器具を検索</h2></div><span className="result-count">{instruments.length} 件</span></div>
                <label className="search-box"><Search size={17} /><input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="器具名・分類・IDで検索" /><kbd>/</kbd></label>
                <div className="catalog-list">
                  {instruments.map((item) => (
                    <div className={`catalog-row ${selected[item.instrument_uid] ? "selected" : ""}`} key={item.instrument_uid}>
                      <div className="instrument-symbol"><Crosshair size={17} /></div>
                      <div className="instrument-name"><strong>{item.name}</strong><span>{item.category_path} · {item.instrument_uid}</span></div>
                      <button className="icon-button add-button" aria-pressed={Boolean(selected[item.instrument_uid])} onClick={() => toggleInstrument(item.instrument_uid)} aria-label={`${item.name}${selected[item.instrument_uid] ? "を解除" : "を追加"}`} title={selected[item.instrument_uid] ? "解除" : "追加"}>{selected[item.instrument_uid] ? <Check size={17} /> : <Plus size={17} />}</button>
                    </div>
                  ))}
                  {instruments.length === 0 && <div className="empty-state">一致する器具がありません</div>}
                </div>
              </div>

              <aside className="declaration-pane">
                <div className="declaration-title"><div><span className="eyebrow">DECLARATION</span><h2>撮影する器具</h2></div><Layers3 size={19} /></div>
                {declaredTypeCount === 0 ? (
                  <div className="declaration-empty"><ImagePlus size={25} /><span>左の一覧から器具を追加</span></div>
                ) : (
                  <div className="declared-list">
                    {Object.keys(selected).map((uid) => {
                      const item = instrumentByUid[uid];
                      if (!item) return null;
                      return <div className="declared-row" key={uid}>
                        <div className="declared-name"><strong>{item.name}</strong><small>{uid}</small></div>
                        <button className="icon-button" onClick={() => toggleInstrument(uid)} aria-label={`${item.name}を宣言から外す`} title="解除"><X size={15} /></button>
                      </div>;
                    })}
                  </div>
                )}
                <div className="declaration-summary"><span>登録器具の種類</span><strong>{String(declaredTypeCount).padStart(2, "0")} <small>種類</small></strong><em>撮影候補</em></div>
                <button className="button button-primary button-wide" onClick={createDeclaration} disabled={busy || declaredTypeCount === 0}>
                  配置確認へ <ArrowRight size={17} />
                </button>
              </aside>
            </section>
          )}

          {step === "confirm" && declaration && (
            <section className="confirm-layout">
              <div className="confirm-copy"><div className="large-step">03</div><span className="eyebrow">ARRANGEMENT CHECK</span><h2>実物と宣言リストを<br />照合してください。</h2><p>カメラの視野内に器具を並べ、数量と種類を確認します。確認後は撮影画面へ進みます。</p></div>
              <div className="confirm-list-panel">
                <div className="confirm-list-head"><span>DECLARED INSTRUMENTS</span><span>{declaration.instrument_type_count} TYPES</span></div>
                {declaration.items.map((item) => {
                  const instrument = instrumentByUid[item.instrument_uid];
                  return <div className="confirm-row" key={item.instrument_uid}><span className="confirm-check"><Check size={14} /></span><div><strong>{instrument?.name ?? item.instrument_uid}</strong><small>{instrument?.category_path ?? ""}</small></div></div>;
                })}
                <div className="confirm-total"><span>タグ付け対象の器具種類</span><strong>{declaration.instrument_type_count}種類</strong></div>
                <div className="confirm-actions"><button className="button button-quiet" onClick={goBack}><ArrowLeft size={16} /> 宣言に戻る</button><button className="button button-primary" onClick={confirmArrangement} disabled={busy}>照合済み・撮影へ <ArrowRight size={16} /></button></div>
              </div>
            </section>
          )}

          {step === "capture" && declaration && (
            <section className="capture-layout">
              <div className="capture-main">
                <div className="capture-toolbar">
                  <div className="camera-state"><span className={`state-indicator ${camera.state}`} /><strong>{camera.state === "ready" ? "カメラ稼働中" : camera.state === "error" ? "接続エラー" : "カメラ未接続"}</strong><span>{camera.camera_name} / {declaration.arrangement_no.toString().padStart(2, "0")}</span></div>
                  <div className="camera-actions">
                    <div className="capture-mode-switch" role="tablist" aria-label="撮影作業モード">
                      <button role="tab" aria-selected={captureMode === "imaging"} className={captureMode === "imaging" ? "selected" : ""} onClick={() => setCaptureMode("imaging")}><Camera size={15} /> 撮像</button>
                      <button role="tab" aria-selected={captureMode === "tagging"} className={captureMode === "tagging" ? "selected" : ""} onClick={() => image && setCaptureMode("tagging")} disabled={!image}><Crosshair size={15} /> タグ付け</button>
                    </div>
                    {captureMode === "imaging" && <>
                      {camera.state !== "ready" && <button className="button button-quiet" onClick={connectCamera} disabled={busy}><RotateCcw size={15} /> 再接続</button>}
                      <button className="button button-capture" onClick={captureImage} disabled={busy || camera.state !== "ready"}><span className="shutter" /> 撮影</button>
                    </>}
                  </div>
                </div>
                {captureMode === "imaging" ? <>
                  <div className="camera-frame">
                    {camera.state === "ready" ? <img className="camera-feed" src={previewUrl} alt="camlibカメラのライブプレビュー" /> : <div className="camera-offline"><div className="offline-mark"><Crosshair size={30} /></div><strong>カメラフィード待機中</strong><span>{camera.error ?? "camlibカメラに接続してください"}</span><button className="button button-primary" onClick={connectCamera} disabled={busy}><Power size={16} /> カメラに接続</button></div>}
                    <div className="frame-corner corner-tl" /><div className="frame-corner corner-tr" /><div className="frame-corner corner-bl" /><div className="frame-corner corner-br" />
                    <span className="frame-label">LIVE / {camera.state === "ready" ? "CONNECTED" : "STANDBY"}</span>
                  </div>
                  <div className="capture-footer"><span>配置 {declaration.arrangement_no} · 候補 {declaration.instrument_type_count}種類</span><button className="text-button" onClick={rearrange} disabled={busy}><RotateCcw size={14} /> 器具を置き直す</button></div>
                </> : <div className="image-review is-focused">
                  <div className="review-heading"><div><span className="eyebrow">CAPTURED IMAGE</span><h2>タグ付け</h2></div>{image && <span className={`tag-status ${image.tag_status}`}>{image.tag_status === "tagged" ? "TAGGED" : "UNTAGGED"}</span>}</div>
                  {image ? <>
                    <div className="tag-image-wrap" onClick={addPoint} role="application" aria-label="画像上をクリックして点を登録">
                      <img src={imageUrl(image.file_url)} alt="撮影画像" />
                      <svg className="point-overlay" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                        {hints.map((hint, index) => {
                          const points = [hint.center, hint.end_a, hint.end_b].filter((point): point is Point => point !== null);
                          return <g key={`${hint.instrument_uid}-${index}`}>
                            {points.length > 1 && <polyline points={points.map((point) => `${point.x * 100},${point.y * 100}`).join(" ")} className="point-line" />}
                            {points.map((point, pointIndex) => <circle key={pointIndex} cx={point.x * 100} cy={point.y * 100} r="1.4" className={`point-dot point-${pointIndex}`} />)}
                          </g>;
                        })}
                      </svg>
                      {image.tag_status === "tagged" && <div className="saved-overlay"><CheckCircle2 size={16} /> 保存済み</div>}
                    </div>
                    <div className="image-metadata">
                      <div><span>撮影カメラ</span><strong>{image.camera_name}</strong></div>
                      <div><span>カメラ状態</span><strong>{image.camera_status}</strong></div>
                      <div><span>撮影場所</span><strong>{image.location || "未設定"}</strong></div>
                      <div><span>取得時刻</span><strong>{new Date(image.captured_at).toLocaleString("ja-JP")}</strong></div>
                    </div>
                    <div className="tag-tools">
                      <label className="tag-select-label" htmlFor="tag-instrument">器具</label>
                      <select id="tag-instrument" value={selectedUid} onChange={(event) => reassignSelectedHint(event.target.value)}>
                        {declaration.items.map((item) => <option key={item.instrument_uid} value={item.instrument_uid}>{instrumentByUid[item.instrument_uid]?.name ?? item.instrument_uid}</option>)}
                      </select>
                      <div className="point-modes" role="group" aria-label="追加する点">
                        {(["center", "end_a", "end_b"] as const).map((kind) => <button key={kind} className={pointKind === kind ? "selected" : ""} onClick={() => setPointKind(kind)} title={`${pointLabels[kind]}を追加`}><span className={`mode-dot ${kind}`} />{pointLabels[kind]}</button>)}
                      </div>
                      <span className="point-count">{hints.length} 点</span>
                    </div>
                    <div className="hint-editor">
                      <div className="hint-editor-heading"><strong>登録タグ</strong><span>{hints.length} 件</span></div>
                      {hints.length === 0 ? <p className="hint-editor-empty">タグはありません。写っている器具を選び、画像をクリックして追加します。</p> : (
                        <div className="hint-list">
                          {hints.map((hint, index) => {
                            const instanceNo = hints.slice(0, index + 1).filter((item) => item.instrument_uid === hint.instrument_uid).length;
                            const instrumentName = instrumentByUid[hint.instrument_uid]?.name ?? hint.instrument_uid;
                            const points = hint.center
                              ? ["中心", hint.end_a && "A", hint.end_b && "B"].filter(Boolean).join(" + ")
                              : hint.visible ? "点なし" : "不可視";
                            return <div className={`hint-row ${selectedHintIndex === index ? "selected" : ""}`} key={`${hint.instrument_uid}-${index}`}>
                              <button className="hint-select" onClick={() => { setSelectedHintIndex(index); setSelectedUid(hint.instrument_uid); }}>
                                <span className="hint-instance"><Crosshair size={14} /> {instrumentName} #{instanceNo}</span>
                                <span className="hint-points">{points}</span>
                              </button>
                              <button className="icon-button hint-delete" onClick={() => removeHint(index)} aria-label={`${instrumentName} #${instanceNo}のタグを削除`} title="タグを削除"><Trash2 size={15} /></button>
                            </div>;
                          })}
                        </div>
                      )}
                      {selectedHintIndex !== null && <span className="hint-edit-note">選択中のタグは画像をクリックして点を修正できます。</span>}
                    </div>
                    <div className="tag-meta-row"><label htmlFor="tagged-by">タグ付け者</label><input id="tagged-by" value={taggedBy} onChange={(event) => setTaggedBy(event.target.value)} placeholder="任意" /><span>{image.width} × {image.height}</span></div>
                    <div className="tag-actions"><button className="button button-quiet" onClick={validateTags} disabled={busy}><CheckCircle2 size={16} /> 検証</button><button className="button button-primary" onClick={saveTags} disabled={busy}><Send size={15} /> タグを保存</button></div>
                    {validation && <div className="validation-list">
                      {validation.errors.map((issue) => <div className="validation-error" key={issue.code}><AlertCircle size={15} /> {issue.message}</div>)}
                      {validation.warnings.map((issue) => <div className="validation-warning" key={issue.code}><AlertCircle size={15} /> {issue.message}</div>)}
                      {validation.errors.length === 0 && validation.warnings.length === 0 && <div className="validation-ok"><CheckCircle2 size={15} /> 検証エラーなし</div>}
                    </div>}
                  </> : <div className="no-image"><ImagePlus size={24} /><span>タグ付けする画像はありません</span><small>撮像モードで画像を撮影してください</small><button className="button button-quiet" onClick={() => setCaptureMode("imaging")}><Camera size={15} /> 撮像モードへ</button></div>}
                </div>}
              </div>

              <aside className="capture-aside">
                <div className="aside-head"><div><span className="eyebrow">DECLARED SET</span><h2>撮影候補</h2></div><span className="item-count">{declaration.instrument_type_count}</span></div>
                <div className="capture-instruments">
                  {declaration.items.map((item, index) => {
                    const instrument = instrumentByUid[item.instrument_uid];
                    const taggedCount = hints.filter((hint) => hint.instrument_uid === item.instrument_uid).length;
                    return <button className={`capture-instrument ${selectedUid === item.instrument_uid ? "selected" : ""}`} key={item.instrument_uid} onClick={() => selectInstrument(item.instrument_uid)}>
                      <span className="capture-instrument-index">{String(index + 1).padStart(2, "0")}</span>
                      <span className="capture-instrument-name"><strong>{instrument?.name ?? item.instrument_uid}</strong><small>{instrument?.category_path ?? item.instrument_uid}</small></span>
                      <span className="tag-progress">{taggedCount}件</span>
                    </button>;
                  })}
                </div>
                <div className="capture-guidance"><span className="eyebrow">POINT SEQUENCE</span><div><span className="sequence-number">1</span><span>中心</span></div><div><span className="sequence-number">2</span><span>端点 A（任意）</span></div><div><span className="sequence-number">3</span><span>端点 B（任意）</span></div><small>画像上の座標は0〜1に正規化して保存されます。</small></div>
                <div className="image-history">
                  <div className="history-title"><span>撮影履歴</span><span>{recentImages.length}</span></div>
                  {recentImages.length === 0 ? <p>まだ撮影画像はありません</p> : recentImages.map((record) => (
                    <button className={`history-row ${image?.image_id === record.image_id ? "selected" : ""}`} key={record.image_id} onClick={() => selectImageForTagging(record)} disabled={busy}>
                      <span className="history-thumb"><Square size={15} /></span>
                      <span><strong>{new Date(record.captured_at).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" })}</strong><small>{record.image_id.slice(0, 8)}</small></span>
                      <span className={record.tag_status === "tagged" ? "history-tagged" : "history-pending"}>{record.tag_status === "tagged" ? "タグ済" : "未タグ"}</span>
                    </button>
                  ))}
                </div>
                <button className="button button-outline button-wide" onClick={() => setCaptureMode("imaging")}><Camera size={15} /> 撮像モードへ戻る</button>
              </aside>
            </section>
          )}

          {step !== "session" && step !== "capture" && <div className="back-link"><button className="text-button" onClick={goBack}><ArrowLeft size={15} /> 前のステップ</button></div>}
          </>}
        </main>
      </div>
      <footer className="statusbar"><span><span className="statusbar-light" /> CAPTURE SYSTEM / LOCAL</span><span>DATA STORED ON API · {new Date().getFullYear()}</span></footer>
    </div>
  );
}

export default App;