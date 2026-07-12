export function Logo({ size = 30, className }: { size?: number; className?: string }) {
  return (
    <img
      className={className}
      src="/dashboard/tenta-logo.png"
      width={size}
      height={size}
      alt="Tenta"
      draggable={false}
    />
  );
}
