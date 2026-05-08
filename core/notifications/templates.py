"""HTML + plaintext templates for the simulation-complete email."""

from __future__ import annotations

from html import escape


def _outcome_label(status: str) -> str:
    return {
        "completed": "completed successfully",
        "failed": "failed",
        "cancelled": "was cancelled",
    }.get(status, f"finished with status '{status}'")


def render_subject(*, name: str, status: str) -> str:
    return f'Your simulation "{name}" {_outcome_label(status)}'


def render_plaintext(
    *,
    name: str,
    status: str,
    workspace_url: str,
    video_url: str | None,
    error_summary: str | None,
    unsubscribe_url: str,
) -> str:
    lines = [
        f'Your simulation "{name}" {_outcome_label(status)}.',
        "",
        f"View it here: {workspace_url}",
    ]
    if video_url:
        lines += ["", f"Watch the rendered video: {video_url}"]
    if status == "failed" and error_summary:
        lines += ["", "Error summary:", error_summary]
    lines += [
        "",
        "— Livestream to AGI",
        "",
        f"Don't want completion emails? Unsubscribe: {unsubscribe_url}",
    ]
    return "\n".join(lines)


def render_html(
    *,
    name: str,
    status: str,
    workspace_url: str,
    video_url: str | None,
    error_summary: str | None,
    unsubscribe_url: str,
) -> str:
    safe_name = escape(name)
    outcome = _outcome_label(status)
    accent = "#22c55e" if status == "completed" else "#ef4444"

    video_block = ""
    if video_url:
        safe_video = escape(video_url, quote=True)
        video_block = (
            f'<p style="margin:16px 0 0;">'
            f'<a href="{safe_video}" '
            f'style="display:inline-block;padding:10px 18px;'
            f'background:#0b5fff;color:#fff;text-decoration:none;'
            f'border-radius:6px;font-weight:600;">Watch the video</a>'
            f"</p>"
            f'<p style="margin:8px 0 0;font-size:13px;color:#64748b;">'
            f'<a href="{safe_video}" style="color:#64748b;">'
            f"{safe_video}</a></p>"
        )

    error_block = ""
    if status == "failed" and error_summary:
        safe_err = escape(error_summary).replace("\n", "<br>")
        error_block = (
            f'<div style="margin-top:16px;padding:12px 14px;'
            f'background:#fef2f2;border-left:3px solid #ef4444;'
            f'font-family:ui-monospace,SFMono-Regular,Menlo,monospace;'
            f'font-size:13px;color:#7f1d1d;white-space:pre-wrap;">'
            f"{safe_err}</div>"
        )

    safe_workspace = escape(workspace_url, quote=True)
    safe_unsub = escape(unsubscribe_url, quote=True)

    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f8fafc;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:#f8fafc;padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0"
       style="background:#ffffff;border-radius:10px;overflow:hidden;
              box-shadow:0 1px 2px rgba(0,0,0,0.04);">
<tr><td style="padding:18px 24px;background:#0f172a;color:#fff;
                font-weight:700;letter-spacing:0.4px;">
  Livestream to AGI
</td></tr>
<tr><td style="padding:24px;color:#0f172a;">
  <p style="margin:0 0 6px;font-size:13px;color:#64748b;">Simulation update</p>
  <h1 style="margin:0 0 12px;font-size:20px;line-height:1.3;">
    "{safe_name}"
    <span style="color:{accent};">{outcome}</span>.
  </h1>
  <p style="margin:0;font-size:15px;color:#334155;">
    Open the workspace to inspect transcripts, costs, and artifacts.
  </p>
  <p style="margin:18px 0 0;">
    <a href="{safe_workspace}"
       style="display:inline-block;padding:10px 18px;background:#0f172a;
              color:#fff;text-decoration:none;border-radius:6px;
              font-weight:600;">Open workspace</a>
  </p>
  {video_block}
  {error_block}
</td></tr>
<tr><td style="padding:14px 24px;background:#f1f5f9;color:#64748b;
                font-size:12px;line-height:1.5;">
  You're receiving this because you submitted a simulation.
  <a href="{safe_unsub}" style="color:#64748b;">Unsubscribe</a> from
  completion emails.
</td></tr>
</table></td></tr></table></body></html>"""
