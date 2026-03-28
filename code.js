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

  // ── Export: selected frame → PNG + annotation JSON ──
  if (msg.type === 'export-frame') {
    const sel = figma.currentPage.selection;
    if (!sel.length) {
      figma.ui.postMessage({ type: 'status', text: 'Select a Frame first' });
      return;
    }
    const node = sel[0];
    if (node.type !== 'FRAME' && node.type !== 'SECTION') {
      figma.ui.postMessage({ type: 'status', text: `Selected "${node.name}" is a ${node.type}, not a Frame` });
      return;
    }

    try {
      // Export PNG
      const png = await node.exportAsync({
        format: 'PNG',
        constraint: { type: 'SCALE', value: 2 }
      });

      // Build annotation JSON from children
      const annotations = [];
      traverseChildren(node, node.x, node.y, annotations);

      const result = {
        frame: node.name,
        w: Math.round(node.width),
        h: Math.round(node.height),
        annotations: annotations
      };

      figma.ui.postMessage({
        type: 'export-result',
        png: Array.from(png),  // Uint8Array → regular array for postMessage
        json: result,
        frameName: node.name
      });
    } catch (e) {
      figma.ui.postMessage({ type: 'status', text: `Export error: ${e.message}` });
    }
  }
};

function traverseChildren(parent, offsetX, offsetY, out) {
  if (!('children' in parent)) return;
  for (const child of parent.children) {
    const rx = Math.round(child.x);
    const ry = Math.round(child.y);

    if (child.type === 'TEXT') {
      out.push({
        type: 'text',
        rx, ry,
        w: Math.round(child.width),
        h: Math.round(child.height),
        content: child.characters,
        name: child.name
      });
    } else if (child.type === 'RECTANGLE') {
      // Check if it's an image fill
      const imgFill = child.fills && child.fills.find(function(f) { return f.type === 'IMAGE'; });
      if (imgFill) {
        out.push({
          type: 'image',
          rx, ry,
          w: Math.round(child.width),
          h: Math.round(child.height),
          name: child.name
        });
      } else {
        out.push({
          type: 'rect',
          rx, ry,
          w: Math.round(child.width),
          h: Math.round(child.height),
          name: child.name
        });
      }
    } else if (child.type === 'LINE') {
      out.push({
        type: 'line',
        rx, ry,
        w: Math.round(child.width),
        h: Math.round(child.height),
        name: child.name
      });
    } else if (child.type === 'VECTOR') {
      out.push({
        type: 'vector',
        rx, ry,
        w: Math.round(child.width),
        h: Math.round(child.height),
        name: child.name
      });
    } else if (child.type === 'FRAME' || child.type === 'GROUP') {
      out.push({
        type: 'group',
        rx, ry,
        w: Math.round(child.width),
        h: Math.round(child.height),
        name: child.name,
        childCount: 'children' in child ? child.children.length : 0
      });
    }
  }
}
