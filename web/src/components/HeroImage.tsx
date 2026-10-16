"use client";

import { useEffect, useState } from "react";

// The Streamlit home's photos (src/ui.py HERO_IMAGE_SOURCES) and captions (app_pages/home.py).
const IMAGES = [
  { src: "https://images.unsplash.com/photo-1552053831-71594a27632d?auto=format&fit=crop&w=1200&q=80", label: "따뜻한 반려동물의 하루" },
  { src: "https://images.unsplash.com/photo-1517849845537-4d257902454a?auto=format&fit=crop&w=1200&q=80", label: "함께 자라는 건강한 일상" },
  { src: "https://images.unsplash.com/photo-1548199973-03cce0bbc87b?auto=format&fit=crop&w=1200&q=80", label: "소중한 가족을 위한 돌봄" },
];
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
        src={failed.has(index) ? FALLBACK : image.src}
        alt="반려견 사진"
        onError={() => setFailed((set) => new Set(set).add(index))}
        className="aspect-[4/3] w-full object-cover"
      />
      <figcaption className="absolute bottom-3 left-3 rounded-full bg-white/90 px-3 py-1 text-sm">{image.label}</figcaption>
    </figure>
  );
}
