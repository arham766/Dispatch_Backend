"use client";

interface PrCardProps {
  prUrl: string;
  proofUrl?: string | null;
  branch?: string;
}

export default function PrCard({ prUrl, proofUrl, branch }: PrCardProps) {
  return (
    <div className="pr-card">
      <div className="pr-card-glow" />
      <div className="pr-card-content">
        <div className="pr-card-header">
          <span className="pr-card-icon">📝</span>
          <h3>Pull Request Ready</h3>
        </div>
        <p className="pr-card-desc">
          A verified fix is waiting for review.
        </p>
        {branch && (
          <div className="pr-card-branch">
            <code>{branch}</code>
          </div>
        )}
        <div className="pr-card-actions">
          <a
            href={prUrl}
            target="_blank"
            rel="noopener"
            className="pr-card-btn pr-card-btn-primary"
          >
            View PR →
          </a>
          {proofUrl && (
            <a
              href={proofUrl}
              target="_blank"
              rel="noopener"
              className="pr-card-btn pr-card-btn-secondary"
            >
              Kane Proof 🎯
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
