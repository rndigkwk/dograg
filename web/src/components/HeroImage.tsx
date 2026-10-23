"use client";

import { useEffect, useState } from "react";

// The Streamlit home's photos (src/ui.py HERO_IMAGE_SOURCES) and captions (app_pages/home.py).
const IMAGES = [
  { id: "1552053831-71594a27632d", label: "따뜻한 반려동물의 하루" },
  { id: "1517849845537-4d257902454a", label: "함께 자라는 건강한 일상" },
  { id: "1548199973-03cce0bbc87b", label: "소중한 가족을 위한 돌봄" },
];
// Unsplash crops to the 4:3 frame and sizes on its side: the plain w=1200 links sent the whole
// portrait photos (1200x1924, 357 kB for the three) to a frame about 440 px wide (2026-10-23).
const WIDTHS = [480, 800, 1200];
const photo = (id: string, width: number) =>
  `https://images.unsplash.com/photo-${id}?auto=format&fit=crop&w=${width}&h=${(width * 3) / 4}&q=75`;
const SIZES = "(min-width: 768px) min(46vw, 520px), 100vw"; // the right column of the home grid
const FALLBACK = "/hero-fallback.svg"; // when the photo service cannot be reached
const INTERVAL_MS = 5000;

/** A photo that changes every few seconds; it stays still for people who ask for reduced motion. */
export default function HeroImage() {
  const [index, setIndex] = useState(0);
  const [failed, setFailed] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(() => setIndex((i) => (i + 1) % IMAGES.length), INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, []);

  const image = IMAGES[index];
  return (
    <figure className="relative overflow-hidden rounded-3xl border border-line bg-white shadow-sm">
      {/* eslint-disable-next-line @next/next/no-img-element -- remote photos with a local fallback; no image optimizer needed */}
      <img
        src={failed.has(index) ? FALLBACK : photo(image.id, 800)}
        srcSet={failed.has(index) ? undefined : WIDTHS.map((w) => `${photo(image.id, w)} ${w}w`).join(", ")}
        sizes={SIZES}
        width={800}
        height={600}
        fetchPriority={index === 0 ? "high" : "auto"}
        alt="반려견 사진"
        onError={() => setFailed((set) => new Set(set).add(index))}
        className="aspect-[4/3] w-full object-cover"
      />
      <figcaption className="absolute bottom-3 left-3 rounded-full bg-white/90 px-3 py-1 text-sm">{image.label}</figcaption>
    </figure>
  );
}
