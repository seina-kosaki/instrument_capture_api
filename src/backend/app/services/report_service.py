"""日次サマリーの生成（JSON + HTML）。StatsService の出力だけを使う。"""
from __future__ import annotations
import html
import json
from pathlib import Path

from .stats_service import StatsService


class ReportService:
    def __init__(self, stats: StatsService, out_dir: Path):
        self._stats, self._out = stats, Path(out_dir)

    def build(self, date: str) -> dict:
        return {"daily": self._stats.daily(date), "coverage": self._stats.coverage()}

    def write_daily(self, date: str) -> dict:
        self._out.mkdir(parents=True, exist_ok=True)
        data = self.build(date)
        jp, hp = self._out / f"daily_{date}.json", self._out / f"daily_{date}.html"
        jp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        hp.write_text(self.render_html(data), encoding="utf-8")
        return {"json": str(jp), "html": str(hp)}

    @staticmethod
    def render_html(data: dict) -> str:
        d, c = data["daily"], data["coverage"]
        e = html.escape

        def bar(v: float) -> str:
            pct = int(round(v * 100))
            return (f'<div class="bar"><div style="width:{pct}%"></div></div><span class="pct">{pct}%</span>')

        today = "".join(
            f"<tr><td>{e(r['name'])}</td><td>{r['images']}</td><td>{r['single_arrangements']}/{r['multi_arrangements']}</td>"
            f"<td>{r['instances']}</td><td>{r['occluded']}</td></tr>" for r in d["instruments"]) or '<tr><td colspan="5">本日の撮影はありません</td></tr>'
        cov = "".join(
            f"<tr><td>{e(r['instrument_uid'])}</td><td>{e(r['name'])}</td><td>{r['images']}</td>"
            f"<td>{r['single_arrangements']}/{c['targets']['single_arrangements']}</td>"
            f"<td>{r['multi_arrangements']}/{c['targets']['multi_arrangements']}</td><td>{bar(r['achievement'])}</td></tr>"
            for r in c["instruments"])
        warn = (f'<p class="warn">未タグ付けの画像が {len(d["untagged_images"])} 枚あります</p>' if d["untagged_images"] else "")
        return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>日次サマリー {e(d['date'])}</title><style>
body{{font-family:Arial,"Hiragino Sans","Yu Gothic",sans-serif;margin:24px;color:#1b2b34;max-width:960px}}
h1{{color:#0b3c49}}h2{{color:#0b3c49;margin-top:32px}}
.kpi{{display:flex;gap:16px;flex-wrap:wrap}}.kpi div{{background:#e8f2f3;border-radius:10px;padding:14px 20px}}
.kpi b{{display:block;font-size:28px;color:#028090}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #d5e2e5;padding:6px 10px;text-align:left}}th{{background:#0b3c49;color:#fff}}
.bar{{display:inline-block;width:120px;height:10px;background:#e8f2f3;border-radius:5px;vertical-align:middle}}
.bar div{{height:10px;background:#028090;border-radius:5px}}.pct{{margin-left:8px}}.warn{{color:#c8402a;font-weight:bold}}
</style></head><body>
<h1>日次サマリー {e(d['date'])}</h1>
<div class="kpi"><div><b>{d['images']}</b>取得枚数</div><div><b>{d['arrangements']}</b>配置数</div>
<div><b>{d['tagged_images']}</b>タグ付け済</div><div><b>{int(c['overall_achievement']*100)}%</b>全体達成率</div></div>
{warn}
<h2>本日の器具別</h2><table><tr><th>器具</th><th>枚数</th><th>配置（単体/複数）</th><th>インスタンス</th><th>遮蔽あり</th></tr>{today}</table>
<h2>全体の取得状態</h2><table><tr><th>uid</th><th>器具</th><th>累計枚数</th><th>単体配置</th><th>複数配置</th><th>達成率</th></tr>{cov}</table>
</body></html>"""
