import Link from "next/link";
import { ShaderBackground } from "@/components/ShaderBackground";

export default function LandingPage() {
  return (
    <div className="relative min-h-screen w-full bg-black">
      <ShaderBackground />
      <div className="relative z-10 min-h-screen flex flex-col items-center justify-center px-6 text-center">
        <h1
          className="text-white font-display tracking-tight leading-none"
          style={{
            fontSize: "clamp(2rem, 4.5vw, 3.5rem)",
            fontWeight: 400,
            letterSpacing: "-0.02em",
            mixBlendMode: "difference",
          }}
        >
          Dispatch
        </h1>
        <Link
          href="/login"
          className="mt-6 font-mono text-xs uppercase tracking-[0.25em] text-white hover:underline underline-offset-[6px] decoration-[1px] transition-colors"
          style={{ mixBlendMode: "difference" }}
        >
          Start
        </Link>
      </div>
    </div>
  );
}
