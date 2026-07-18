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
        ctx.fillStyle = "rgba(124, 190, 232, 0.45)";
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    const step = () => {
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

    const start = () => {
      cancelAnimationFrame(raf);
      resize();
      seed();
      if (reducedMotion.matches) {
        // One settled frame — the mesh stays as texture, it just doesn't move.
        draw();
      } else {
        raf = requestAnimationFrame(step);
      }
    };

    start();
    window.addEventListener("resize", start);
    reducedMotion.addEventListener("change", start);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", start);
      reducedMotion.removeEventListener("change", start);
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
