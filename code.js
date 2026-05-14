// Whiteboard Bridge — Figma Plugin (Sandbox)
figma.showUI(__html__, { width: 300, height: 360 });

figma.ui.onmessage = async (msg) => {

  // ── Screenshot: receive image bytes from UI, insert into canvas ──
  if (msg.type === 'insert-screenshot') {
    try {
      const bytes = new Uint8Array(msg.data);
      const image = figma.createImage(bytes);
      const rect = figma.createRectangle();

      // Default phone screen size on canvas
      const w = msg.width || 360;
      const h = msg.height || 780;
      rect.resize(w, h);
      rect.fills = [{ type: 'IMAGE', imageHash: image.hash, scaleMode: 'FILL' }];
      rect.name = msg.filename || 'screenshot';

      // Place near viewport center or next to existing selection
      const vp = figma.viewport.center;
      rect.x = vp.x - w / 2;
      rect.y = vp.y - h / 2;

      figma.currentPage.appendChild(rect);
      figma.currentPage.selection = [rect];
      figma.viewport.scrollAndZoomIntoView([rect]);

      figma.ui.postMessage({ type: 'status', text: `Inserted: ${rect.name}` });
    } catch (e) {
      figma.ui.postMessage({ type: 'status', text: `Error: ${e.message}` });
    }
  }
};
