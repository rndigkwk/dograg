export default function PageHeader({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return (
    <header className="py-6">
      <p className="text-sm font-semibold text-accent">{eyebrow}</p>
      <h1 className="text-2xl font-bold text-ink">{title}</h1>
      <p className="mt-1 text-sm text-muted">{description}</p>
    </header>
  );
}
