const DEFAULT_TITLE = "Helios";

function loadingHtml(title: string, detail: string): string {
  const safeTitle = title.replace(/[<>&"]/g, "");
  const safeDetail = detail.replace(/[<>&"]/g, "");
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>${safeTitle}</title>
    <style>
      :root { color-scheme: dark; }
      body {
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: #07101a;
        color: #f8fafc;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      .card {
        max-width: 440px;
        padding: 28px 32px;
        border-radius: 20px;
        background: rgba(15, 23, 42, 0.92);
        border: 1px solid rgba(148, 163, 184, 0.2);
        box-shadow: 0 30px 80px rgba(2, 6, 23, 0.45);
      }
      h1 {
        margin: 0 0 12px;
        font-size: 22px;
        line-height: 1.2;
      }
      p {
        margin: 0;
        color: rgba(226, 232, 240, 0.8);
        line-height: 1.5;
      }
    </style>
  </head>
  <body>
    <div class="card">
      <h1>${safeTitle}</h1>
      <p>${safeDetail}</p>
    </div>
  </body>
</html>`;
}

export function openPendingWindow(title = DEFAULT_TITLE, detail = "Preparing the requested artifact."): Window | null {
  const popup = window.open("", "_blank", "noopener,noreferrer");
  if (!popup) return null;
  popup.document.open();
  popup.document.write(loadingHtml(title, detail));
  popup.document.close();
  return popup;
}

export function navigatePendingWindow(popup: Window | null, url: string): void {
  if (popup && !popup.closed) {
    popup.location.replace(url);
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

export function closePendingWindow(popup: Window | null): void {
  if (popup && !popup.closed) {
    popup.close();
  }
}
