"use client";

import { useEffect, useRef } from "react";

// ── Loom background ───────────────────────────────────────────────────────
// The hero's signature element: a slowly reconfiguring node/thread mesh.
// The metaphor is literal to Nimbus — nodes are resources/agents, threads are
// the connections between them, and the graph quietly redraws itself the way
// the agents rework infrastructure. Canvas2D on purpose: the reference
// component (21st.dev digital-loom) is Canvas2D too, and Three.js wouldn't
// earn its bundle weight for dots and lines.

const NODE_COUNT = 44;
const LINK_DIST = 210;
const DRIFT = 0.16; // px per frame at 60fps — barely perceptible motion
const CURSOR_DIST = 200; // radius within which the mesh reacts to the pointer
const PARALLAX = 14; // max px the field drifts toward the cursor
const EASE = 0.06; // how quickly parallax/cursor state catches up (lower = smoother)

type Node = { x: number; y: number; vx: number; vy: number; r: number };

export default function LoomBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let width = 0;
    let height = 0;
    let nodes: Node[] = [];
    let raf = 0;

    // Cursor state. `px/py` is the raw pointer (canvas-local); `ox/oy` is the
    // eased parallax offset applied to the whole field so it glides rather than
    // snaps. `active` gates all cursor-reactive drawing so the mesh is inert
    // until the pointer is actually over the hero.
    let px = -9999;
    let py = -9999;
    let ox = 0;
    let oy = 0;
    let active = false;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const rect = canvas.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const seed = () => {
      nodes = Array.from({ length: NODE_COUNT }, () => {
        const angle = Math.random() * Math.PI * 2;
        return {
          x: Math.random() * width,
          y: Math.random() * height,
          vx: Math.cos(angle) * DRIFT,
          vy: Math.sin(angle) * DRIFT,
          r: 1.2 + Math.random() * 1.1,
        };
      });
    };

    const draw = () => {
      ctx.clearRect(0, 0, width, height);
      // The whole field is offset by the eased parallax so it drifts toward the
      // cursor as one plane; cursor math below uses the same offset so links to
      // the pointer stay accurate.
      const mx = px - ox;
      const my = py - oy;

      ctx.save();
      ctx.translate(ox, oy);

      // Threads first, under the nodes. Alpha falls off with distance so
      // links fade in/out as the graph reconfigures instead of popping.
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const d = Math.hypot(dx, dy);
          if (d < LINK_DIST) {
            const a = (1 - d / LINK_DIST) * 0.14;
            ctx.strokeStyle = `rgba(93, 187, 242, ${a})`;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(nodes[i].x, nodes[i].y);
            ctx.lineTo(nodes[j].x, nodes[j].y);
            ctx.stroke();
          }
        }
      }

      for (const n of nodes) {
        // Nodes near the cursor brighten and thread toward it — the mesh
        // "notices" the pointer, reinforcing the living-graph metaphor.
        let glow = 0;
        if (active) {
          const cd = Math.hypot(n.x - mx, n.y - my);
          if (cd < CURSOR_DIST) {
            glow = 1 - cd / CURSOR_DIST;
            ctx.strokeStyle = `rgba(93, 187, 242, ${glow * 0.35})`;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(n.x, n.y);
            ctx.lineTo(mx, my);
            ctx.stroke();
          }
        }
        ctx.fillStyle = `rgba(124, 190, 232, ${0.45 + glow * 0.45})`;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r + glow * 1.3, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.restore();
    };

    const step = () => {
      // Ease the field toward a small offset proportional to how far the cursor
      // sits from center — pure parallax, no layout impact.
      const targetX = active ? ((px / width) - 0.5) * -2 * PARALLAX : 0;
      const targetY = active ? ((py / height) - 0.5) * -2 * PARALLAX : 0;
      ox += (targetX - ox) * EASE;
      oy += (targetY - oy) * EASE;

      for (const n of nodes) {
        n.x += n.vx;
        n.y += n.vy;
        // Wrap instead of bounce — no visible "wall" at the edges, threads to
        // an exiting node simply fade as it drifts out of link range.
        if (n.x < -10) n.x = width + 10;
        if (n.x > width + 10) n.x = -10;
        if (n.y < -10) n.y = height + 10;
        if (n.y > height + 10) n.y = -10;
      }
      draw();
      raf = requestAnimationFrame(step);
    };

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

    // Pointer tracking is mapped into canvas-local coords. The canvas is
    // pointer-events-none (it sits behind the hero content), so we listen on
    // the window and translate against the canvas rect.
    const onPointerMove = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      px = e.clientX - rect.left;
      py = e.clientY - rect.top;
      active = px >= 0 && px <= width && py >= 0 && py <= height;
    };
    const onPointerLeave = () => {
      active = false;
    };

    const start = () => {
      cancelAnimationFrame(raf);
      resize();
      seed();
      if (reducedMotion.matches) {
        // One settled frame — the mesh stays as texture, it just doesn't move,
        // and it does NOT react to the pointer.
        active = false;
        ox = 0;
        oy = 0;
        draw();
      } else {
        raf = requestAnimationFrame(step);
      }
    };

    start();
    window.addEventListener("resize", start);
    reducedMotion.addEventListener("change", start);
    window.addEventListener("pointermove", onPointerMove, { passive: true });
    window.addEventListener("pointerleave", onPointerLeave);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", start);
      reducedMotion.removeEventListener("change", start);
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerleave", onPointerLeave);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className="pointer-events-none absolute left-1/2 top-0 h-full w-screen -translate-x-1/2"
      style={{
        // Fade the mesh toward the edges so it reads as ambient depth behind
        // the content, not a pattern with a hard boundary.
        maskImage: "radial-gradient(ellipse 75% 70% at 50% 45%, black 35%, transparent 100%)",
        WebkitMaskImage: "radial-gradient(ellipse 75% 70% at 50% 45%, black 35%, transparent 100%)",
      }}
    />
  );
}
