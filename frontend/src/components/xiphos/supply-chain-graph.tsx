/**
 * Supply Chain Visualization
 *
 * Renders a force-directed graph of awardee and subcontractor
 * relationships from vehicle-search results.
 */

import { useRef, useEffect, useState } from "react";
import { T } from "@/lib/tokens";
import type { VehicleSearchResult, VehicleVendor } from "@/lib/api";

const GOLD = "#C4A052";

interface SupplyChainGraphProps {
  data: VehicleSearchResult;
  onSelectVendor: (vendor: VehicleVendor) => void;
  width?: number;
  height?: number;
}

interface GraphNode {
  id: string;
  label: string;
  role: "prime" | "sub" | "vehicle";
  x: number;
  y: number;
  vx: number;
  vy: number;
  amount?: number;
  vendor?: VehicleVendor;
}

interface GraphEdge {
  source: string;
  target: string;
}

export function SupplyChainGraph({ data, onSelectVendor, width = 720, height = 480 }: SupplyChainGraphProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const nodesRef = useRef<GraphNode[]>([]);
  const edgesRef = useRef<GraphEdge[]>([]);
  const animRef = useRef<number>(0);

  useEffect(() => {
    // Build graph data
    const nodes: GraphNode[] = [];
    const edges: GraphEdge[] = [];
    const seen = new Set<string>();

    // Vehicle center node
    const vehicleId = `vehicle_${data.vehicle_name}`;
    nodes.push({
      id: vehicleId,
      label: data.vehicle_name,
      role: "vehicle",
      x: width / 2,
      y: height / 2,
      vx: 0, vy: 0,
    });

    // Prime contractor nodes
    for (const p of data.primes.slice(0, 12)) {
      const pid = `prime_${p.vendor_name}`;
      if (seen.has(pid)) continue;
      seen.add(pid);

      const angle = (nodes.length / Math.max(data.primes.length, 1)) * Math.PI * 2;
      nodes.push({
        id: pid,
        label: p.vendor_name.length > 25 ? p.vendor_name.slice(0, 22) + "..." : p.vendor_name,
        role: "prime",
        x: width / 2 + Math.cos(angle) * 160 + (Math.random() - 0.5) * 40,
        y: height / 2 + Math.sin(angle) * 130 + (Math.random() - 0.5) * 40,
        vx: 0, vy: 0,
        amount: p.award_amount,
        vendor: p,
      });
      edges.push({ source: vehicleId, target: pid });
    }

    // Subcontractor nodes
    for (const s of data.subs.slice(0, 15)) {
      const sid = `sub_${s.vendor_name}`;
      if (seen.has(sid)) continue;
      seen.add(sid);

      // Link to prime if known
      const primeId = s.prime_recipient ? `prime_${s.prime_recipient}` : vehicleId;
      const targetExists = nodes.some(n => n.id === primeId);

      const angle = (nodes.length / Math.max(data.subs.length + data.primes.length, 1)) * Math.PI * 2;
      nodes.push({
        id: sid,
        label: s.vendor_name.length > 22 ? s.vendor_name.slice(0, 19) + "..." : s.vendor_name,
        role: "sub",
        x: width / 2 + Math.cos(angle) * 220 + (Math.random() - 0.5) * 60,
        y: height / 2 + Math.sin(angle) * 180 + (Math.random() - 0.5) * 60,
        vx: 0, vy: 0,
        amount: s.award_amount,
        vendor: s,
      });
      edges.push({ source: targetExists ? primeId : vehicleId, target: sid });
    }

    nodesRef.current = nodes;
    edgesRef.current = edges;

    // Simple force simulation
    let frame = 0;
    const simulate = () => {
      const ns = nodesRef.current;
      const es = edgesRef.current;

      // Repulsion between all nodes
      for (let i = 0; i < ns.length; i++) {
        for (let j = i + 1; j < ns.length; j++) {
          const dx = ns[j].x - ns[i].x;
          const dy = ns[j].y - ns[i].y;
          const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
          const force = 800 / (dist * dist);
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          ns[i].vx -= fx; ns[i].vy -= fy;
          ns[j].vx += fx; ns[j].vy += fy;
        }
      }

      // Attraction along edges
      for (const e of es) {
        const s = ns.find(n => n.id === e.source);
        const t = ns.find(n => n.id === e.target);
        if (!s || !t) continue;
        const dx = t.x - s.x;
        const dy = t.y - s.y;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const idealDist = s.role === "vehicle" || t.role === "vehicle" ? 140 : 100;
        const force = (dist - idealDist) * 0.02;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        s.vx += fx; s.vy += fy;
        t.vx -= fx; t.vy -= fy;
      }

      // Center gravity
      for (const n of ns) {
        n.vx += (width / 2 - n.x) * 0.003;
        n.vy += (height / 2 - n.y) * 0.003;
      }

      // Apply velocity with damping
      const damping = frame < 60 ? 0.85 : 0.92;
      for (const n of ns) {
        if (n.role === "vehicle") { n.x = width / 2; n.y = height / 2; continue; }
        n.vx *= damping; n.vy *= damping;
        n.x += n.vx; n.y += n.vy;
        // Bounds
        n.x = Math.max(60, Math.min(width - 60, n.x));
        n.y = Math.max(40, Math.min(height - 40, n.y));
      }

      // Draw
      const ctx = canvasRef.current?.getContext("2d");
      if (!ctx) return;

      ctx.clearRect(0, 0, width, height);

      // Edges
      for (const e of es) {
        const s = ns.find(n => n.id === e.source);
        const t = ns.find(n => n.id === e.target);
        if (!s || !t) continue;
        ctx.beginPath();
        ctx.moveTo(s.x, s.y);
        ctx.lineTo(t.x, t.y);
        ctx.strokeStyle = t.role === "sub" ? "rgba(245,158,11,0.2)" : "rgba(196,160,82,0.3)";
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Nodes
      for (const n of ns) {
        const isHovered = hoveredNode?.id === n.id;
        let radius = n.role === "vehicle" ? 28 : n.role === "prime" ? 16 : 10;
        if (isHovered) radius += 3;

        // Node circle
        ctx.beginPath();
        ctx.arc(n.x, n.y, radius, 0, Math.PI * 2);
        if (n.role === "vehicle") {
          ctx.fillStyle = GOLD;
        } else if (n.role === "prime") {
          ctx.fillStyle = isHovered ? "#3b82f6" : "#1e3a5f";
        } else {
          ctx.fillStyle = isHovered ? "#f59e0b" : "#92400e";
        }
        ctx.fill();
        ctx.strokeStyle = isHovered ? "#fff" : "rgba(255,255,255,0.2)";
        ctx.lineWidth = isHovered ? 2 : 1;
        ctx.stroke();

        // Label
        ctx.fillStyle = isHovered ? "#fff" : "rgba(255,255,255,0.7)";
        ctx.font = n.role === "vehicle" ? "bold 11px sans-serif" : "10px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(n.label, n.x, n.y + radius + 14);

        // Amount badge for hovered
        if (isHovered && n.amount) {
          const amtText = `$${(n.amount / 1e6).toFixed(1)}M`;
          ctx.fillStyle = "rgba(0,0,0,0.7)";
          ctx.fillRect(n.x - 28, n.y - radius - 22, 56, 16);
          ctx.fillStyle = "#4ade80";
          ctx.font = "bold 10px sans-serif";
          ctx.fillText(amtText, n.x, n.y - radius - 10);
        }
      }

      frame++;
      if (frame < 200) {
        animRef.current = requestAnimationFrame(simulate);
      }
    };

    animRef.current = requestAnimationFrame(simulate);
    return () => cancelAnimationFrame(animRef.current);
  }, [data, width, height, hoveredNode]);

  const handleCanvasMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    let found: GraphNode | null = null;
    for (const n of nodesRef.current) {
      const r = n.role === "vehicle" ? 28 : n.role === "prime" ? 16 : 10;
      const dx = mx - n.x;
      const dy = my - n.y;
      if (dx * dx + dy * dy < (r + 4) * (r + 4)) {
        found = n;
        break;
      }
    }
    setHoveredNode(found);
  };

  const handleCanvasClick = () => {
    if (hoveredNode?.vendor) {
      onSelectVendor(hoveredNode.vendor);
    }
  };

  return (
    <div style={{ position: "relative" }}>
      <canvas
        ref={canvasRef}
        width={width}
        height={height}
        style={{ borderRadius: 12, border: `1px solid ${T.border}`, background: T.bg, cursor: hoveredNode ? "pointer" : "default" }}
        onMouseMove={handleCanvasMove}
        onClick={handleCanvasClick}
      />

      {/* Legend */}
      <div style={{ display: "flex", gap: 16, justifyContent: "center", marginTop: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: T.muted }}>
          <div style={{ width: 12, height: 12, borderRadius: 6, background: GOLD }} />
          Contract Vehicle
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: T.muted }}>
          <div style={{ width: 10, height: 10, borderRadius: 5, background: "#1e3a5f" }} />
          Prime Contractor
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: T.muted }}>
          <div style={{ width: 8, height: 8, borderRadius: 4, background: "#92400e" }} />
          Subcontractor
        </div>
      </div>

      {/* Tooltip */}
      {hoveredNode && hoveredNode.role !== "vehicle" && (
        <div style={{
          position: "absolute", bottom: 50, left: "50%", transform: "translateX(-50%)",
          padding: "8px 14px", borderRadius: 8, background: "rgba(0,0,0,0.85)", color: "#fff",
          fontSize: 12, whiteSpace: "nowrap", pointerEvents: "none",
        }}>
          <strong>{hoveredNode.label}</strong>
          {hoveredNode.amount ? ` | $${(hoveredNode.amount / 1e6).toFixed(1)}M` : ""}
          {" | Click to create case"}
        </div>
      )}
    </div>
  );
}
