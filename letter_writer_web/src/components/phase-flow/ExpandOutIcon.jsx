/** Outward arrows — expand column to overlay (compact icon button). */
export default function ExpandOutIcon({ size = 14 }) {
  const s = size;
  return (
    <svg
      width={s}
      height={s}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M6 2H2v4M10 2h4v4M10 14h4v-4M6 14H2v-4" />
    </svg>
  );
}
