import { useEffect, useState } from "react";
import { AlertCircle, BarChart3, CalendarDays, Download, ExternalLink, FileText, ImagePlus, RefreshCw } from "lucide-react";
import { API_BASE, apiRequest, imageUrl, type ApiError } from "./api";

type AnalysisTab = "coverage" | "daily";

type InstrumentCoverage = {
  instrument_uid: string;
  name: string;
  name_ja: string;
  model_number: string | null;
  sample_image_url: string | null;
  images: number;
  single_images: number;
  multi_images: number;
  tagged_images: number;
  instances: number;
  occluded: number;
  single_arrangements: number;
  multi_arrangements: number;
  sessions: number;
  achievement: number;
};

type CoverageData = {
  targets: { single_arrangements: number; multi_arrangements: number };
  total_images: number;
  overall_achievement: number;
  instruments: InstrumentCoverage[];
  next_to_shoot: string[];
};

type DailyData = {
  date: string;
  images: number;
  tagged_images: number;
  untagged_images: string[];
  arrangements: number;
  sessions: string[];
  instruments: InstrumentCoverage[];
};

function localDate(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function formatError(error: unknown): string {
  if (error instanceof Error && "issues" in error) {
    const apiError = error as ApiError;
    if (apiError.issues.length > 0) {
      return `${apiError.message}: ${apiError.issues.map((issue) => issue.message).join(" / ")}`;
    }
  }
  return error instanceof Error ? error.message : "解析データを取得できませんでした";
}

function escapeCsv(value: unknown): string {
  const text = value == null ? "" : String(value);
  return `"${text.replaceAll('"', '""')}"`;
}

function downloadCsv(rows: Array<Record<string, unknown>>, date: string): void {
  if (rows.length === 0) throw new Error("出力するタグデータがありません");
  const headers = Object.keys(rows[0]);
  const csv = [headers, ...rows.map((row) => headers.map((header) => row[header]))]
    .map((values) => values.map(escapeCsv).join(","))
    .join("\r\n");
  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `hints_${date || "all"}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function AnalysisView() {
  const [tab, setTab] = useState<AnalysisTab>("coverage");
  const [date, setDate] = useState(localDate);
  const [coverage, setCoverage] = useState<CoverageData | null>(null);
  const [daily, setDaily] = useState<DailyData | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [loading, setLoading] = useState(false);
  const [action, setAction] = useState("");
  const [error, setError] = useState("");
  const [reportUrl, setReportUrl] = useState("");
  const [sampleImageFailures, setSampleImageFailures] = useState<Record<string, true>>({});

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const request = tab === "coverage"
      ? apiRequest<CoverageData>("/stats/coverage", { signal: controller.signal }).then(setCoverage)
      : apiRequest<DailyData>(`/stats/daily?date=${encodeURIComponent(date)}`, { signal: controller.signal }).then(setDaily);
    request
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(formatError(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [tab, date, refreshVersion]);

  async function exportHints(): Promise<void> {
    setAction("export");
    setError("");
    try {
      const query = tab === "daily" ? `?date=${encodeURIComponent(date)}` : "";
      const rows = await apiRequest<Array<Record<string, unknown>>>(`/export/hints${query}`);
      downloadCsv(rows, tab === "daily" ? date : "all");
      setAction("CSVをダウンロードしました");
    } catch (cause) {
      setError(formatError(cause));
      setAction("");
    }
  }

  async function generateReport(): Promise<void> {
    setAction("report");
    setError("");
    try {
      const query = `?date=${encodeURIComponent(date)}`;
      await apiRequest<Record<string, string>>(`/reports/daily${query}`, { method: "POST" });
      setReportUrl(`${API_BASE}/reports/daily${query}`);
      setAction("日次レポートを生成しました");
    } catch (cause) {
      setError(formatError(cause));
      setAction("");
    }
  }

  const rows = tab === "coverage" ? coverage?.instruments ?? [] : daily?.instruments ?? [];
  const targets = coverage?.targets;
  const nextNames = new Map((coverage?.instruments ?? []).map((row) => [row.instrument_uid, row.name]));

  return (
    <section className="analysis-view">
      <div className="analysis-toolbar">
        <div className="analysis-tabs" role="tablist" aria-label="解析ビュー">
          <button role="tab" aria-selected={tab === "coverage"} className={tab === "coverage" ? "selected" : ""} onClick={() => setTab("coverage")}><BarChart3 size={15} /> 達成状況</button>
          <button role="tab" aria-selected={tab === "daily"} className={tab === "daily" ? "selected" : ""} onClick={() => setTab("daily")}><CalendarDays size={15} /> 日次集計</button>
        </div>
        <div className="analysis-actions">
          {tab === "daily" && <label className="analysis-date"><span>対象日</span><input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label>}
          <button className="button button-quiet" onClick={() => void exportHints()} disabled={loading || action === "export"}><Download size={15} /> タグCSV</button>
          {tab === "daily" && <button className="button button-primary" onClick={() => void generateReport()} disabled={loading || action === "report"}><FileText size={15} /> レポート生成</button>}
          <button className="icon-button analysis-refresh" onClick={() => setRefreshVersion((current) => current + 1)} disabled={loading} title="再読み込み" aria-label="再読み込み"><RefreshCw size={15} /></button>
        </div>
      </div>

      {error && <div className="alert alert-error" role="alert"><AlertCircle size={17} /><span>{error}</span><button onClick={() => setError("")} aria-label="エラーを閉じる">×</button></div>}
      {action && action !== "export" && action !== "report" && <div className="analysis-feedback" role="status">{action}{reportUrl && <a href={reportUrl} target="_blank" rel="noreferrer">HTMLを開く <ExternalLink size={13} /></a>}</div>}
      {loading ? <div className="analysis-loading">集計データを読み込み中…</div> : tab === "coverage" ? (
        <>
          <div className="analysis-kpis">
            <div><span>全体達成率</span><strong>{Math.round((coverage?.overall_achievement ?? 0) * 100)}<small>%</small></strong></div>
            <div><span>保存画像</span><strong>{coverage?.total_images ?? 0}<small> 枚</small></strong></div>
            <div><span>器具種類</span><strong>{coverage?.instruments.length ?? 0}<small> 種</small></strong></div>
            <div><span>次に撮影</span><strong className="next-instrument">{coverage?.next_to_shoot.map((uid) => nextNames.get(uid) ?? uid).slice(0, 2).join("、") || "目標達成"}</strong></div>
          </div>
          <div className="analysis-table-wrap">
            <table className="analysis-table">
              <thead><tr><th>器具</th><th>画像</th><th>単体配置</th><th>複数配置</th><th>タグ</th><th>遮蔽</th><th>達成率</th></tr></thead>
              <tbody>{rows.map((row) => <tr key={row.instrument_uid}>
                <td className="analysis-instrument-cell">
                  <div className="analysis-instrument-display">
                    {row.sample_image_url && !sampleImageFailures[row.instrument_uid] ? (
                      <img
                        className="instrument-thumbnail"
                        src={imageUrl(row.sample_image_url)}
                        alt={`${row.name_ja || row.name} サンプル画像`}
                        onError={() => setSampleImageFailures((current) => ({ ...current, [row.instrument_uid]: true }))}
                      />
                    ) : (
                      <div className="instrument-thumbnail instrument-thumbnail-empty" aria-label="サンプル画像なし">
                        <ImagePlus size={17} />
                        <span>画像なし</span>
                      </div>
                    )}
                    <div className="analysis-instrument-name">
                      <strong>{row.name || "未登録"}</strong>
                      <span>日本語名: {row.name_ja || "未登録"}</span>
                      <span>型番: {row.model_number || "未登録"}</span>
                      <small>{row.instrument_uid}</small>
                    </div>
                  </div>
                </td>
                <td>{row.images}</td>
                <td>{row.single_arrangements}<span className="target-count"> / {targets?.single_arrangements ?? "—"}</span></td>
                <td>{row.multi_arrangements}<span className="target-count"> / {targets?.multi_arrangements ?? "—"}</span></td>
                <td>{row.instances}</td><td>{row.occluded}</td>
                <td><div className="coverage-cell"><div className="coverage-track"><span style={{ width: `${Math.min(100, row.achievement * 100)}%` }} /></div><strong>{Math.round(row.achievement * 100)}%</strong></div></td>
              </tr>)}</tbody>
            </table>
            {rows.length === 0 && <div className="analysis-empty">集計対象の器具がありません</div>}
          </div>
        </>
      ) : (
        <>
          <div className="analysis-kpis">
            <div><span>取得枚数</span><strong>{daily?.images ?? 0}<small> 枚</small></strong></div>
            <div><span>タグ済み</span><strong>{daily?.tagged_images ?? 0}<small> 枚</small></strong></div>
            <div><span>配置数</span><strong>{daily?.arrangements ?? 0}<small> 配置</small></strong></div>
            <div><span>セッション</span><strong>{daily?.sessions.length ?? 0}<small> 件</small></strong></div>
          </div>
          {daily && daily.untagged_images.length > 0 && <div className="untagged-notice">未タグ画像 {daily.untagged_images.length}枚: {daily.untagged_images.join("、")}</div>}
          <div className="analysis-table-wrap">
            <table className="analysis-table">
              <thead><tr><th>器具</th><th>画像</th><th>単体配置</th><th>複数配置</th><th>タグ</th><th>遮蔽</th></tr></thead>
              <tbody>{rows.map((row) => <tr key={row.instrument_uid}>
                <td className="analysis-instrument-cell">
                  <div className="analysis-instrument-display">
                    {row.sample_image_url && !sampleImageFailures[row.instrument_uid] ? (
                      <img
                        className="instrument-thumbnail"
                        src={imageUrl(row.sample_image_url)}
                        alt={`${row.name_ja || row.name} サンプル画像`}
                        onError={() => setSampleImageFailures((current) => ({ ...current, [row.instrument_uid]: true }))}
                      />
                    ) : (
                      <div className="instrument-thumbnail instrument-thumbnail-empty" aria-label="サンプル画像なし">
                        <ImagePlus size={17} />
                        <span>画像なし</span>
                      </div>
                    )}
                    <div className="analysis-instrument-name">
                      <strong>{row.name || "未登録"}</strong>
                      <span>日本語名: {row.name_ja || "未登録"}</span>
                      <span>型番: {row.model_number || "未登録"}</span>
                      <small>{row.instrument_uid}</small>
                    </div>
                  </div>
                </td>
                <td>{row.images}</td><td>{row.single_arrangements}</td><td>{row.multi_arrangements}</td><td>{row.instances}</td><td>{row.occluded}</td>
              </tr>)}</tbody>
            </table>
            {rows.length === 0 && <div className="analysis-empty">この日の撮影はありません</div>}
          </div>
        </>
      )}
    </section>
  );
}

export default AnalysisView;