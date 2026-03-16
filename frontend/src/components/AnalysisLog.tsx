import React, { useState } from "react";
import { Check, Info, AlertTriangle, XCircle, ChevronRight, ChevronDown, Search } from "lucide-react";
import { AnalysisStep } from "../types";

interface Props {
  analysis: AnalysisStep[];
  filename: string;
  positionDebug?: string[];
}

/**
 * Groups analysis steps into collapsible sections.
 * A "section" type step starts a new group; subsequent "detail" steps belong to it.
 * Non-section, non-detail steps stay at the top level.
 */
function groupAnalysisSteps(analysis: AnalysisStep[]) {
  const groups: Array<
    | { kind: "step"; step: AnalysisStep; index: number }
    | { kind: "section"; title: string; steps: Array<{ step: AnalysisStep; index: number }>; sectionIndex: number }
  > = [];

  let currentSection: { title: string; steps: Array<{ step: AnalysisStep; index: number }>; sectionIndex: number } | null = null;

  const flushSection = () => {
    if (currentSection) {
      groups.push({
        kind: "section" as const,
        title: currentSection.title,
        steps: currentSection.steps,
        sectionIndex: currentSection.sectionIndex,
      });
      currentSection = null;
    }
  };

  analysis.forEach((step, i) => {
    if (step.type === "section") {
      flushSection();
      currentSection = { title: step.message, steps: [], sectionIndex: i };
    } else if (step.type === "detail" && currentSection) {
      currentSection.steps.push({ step, index: i });
    } else {
      flushSection();
      groups.push({ kind: "step" as const, step, index: i });
    }
  });

  flushSection();

  return groups;
}

/**
 * Renders a detail message with inline color-coded tags.
 * Recognizes patterns like [TEXT+GEOMETRY], [GEOMETRY-ONLY], [TEXT], [GEOM], [REF], etc.
 */
function DetailMessage({ message }: { message: string }) {
  // Split on bracket-tags and colorize them
  const TAG_COLORS: Record<string, { bg: string; fg: string }> = {
    "TEXT+GEOMETRY": { bg: "#D4EDDA", fg: "#155724" },
    "TEXT-ONLY": { bg: "#D4EDDA", fg: "#155724" },
    "GEOMETRY-ONLY": { bg: "#FFF3CD", fg: "#856404" },
    "NESTED-REFS-ONLY": { bg: "#D6E9F8", fg: "#0C5460" },
    "EMPTY": { bg: "#E2E3E5", fg: "#383D41" },
    "OTHER": { bg: "#E2E3E5", fg: "#383D41" },
    "HAS-TEXT": { bg: "#D4EDDA", fg: "#155724" },
    "NO-TEXT": { bg: "#F8D7DA", fg: "#721C24" },
    "TEXT": { bg: "#D4EDDA", fg: "#155724" },
    "GEOM": { bg: "#FFF3CD", fg: "#856404" },
    "REF": { bg: "#D6E9F8", fg: "#0C5460" },
  };

  const parts = message.split(/(\[[A-Z][A-Z0-9+\-_]*\])/g);

  return (
    <span className="analysis-detail-message">
      {parts.map((part, i) => {
        const tagMatch = part.match(/^\[([A-Z][A-Z0-9+\-_]*)\]$/);
        if (tagMatch) {
          const tagName = tagMatch[1];
          const colors = TAG_COLORS[tagName];
          if (colors) {
            return (
              <span
                key={i}
                style={{
                  background: colors.bg,
                  color: colors.fg,
                  padding: "1px 5px",
                  borderRadius: 3,
                  fontSize: "10px",
                  fontWeight: 600,
                  marginRight: 4,
                  whiteSpace: "nowrap",
                }}
              >
                {tagName}
              </span>
            );
          }
        }
        return <span key={i}>{part}</span>;
      })}
    </span>
  );
}

function CollapsibleSection({
  title,
  steps,
  sectionIndex,
  filter,
}: {
  title: string;
  steps: Array<{ step: AnalysisStep; index: number }>;
  sectionIndex: number;
  filter: string;
}) {
  // Auto-expand sections that contain diagnostic keywords
  const isAnatomySection = title.includes("ANATOMY") || title.includes("VERDICT") || title.includes("NESTED BLOCK");
  const [expanded, setExpanded] = useState(isAnatomySection);

  // Filter steps if there's a search query
  const filteredSteps = filter
    ? steps.filter((s) => s.step.message.toLowerCase().includes(filter.toLowerCase()))
    : steps;

  // If filtering and no matches in this section (and title doesn't match), hide it
  if (filter && filteredSteps.length === 0 && !title.toLowerCase().includes(filter.toLowerCase())) {
    return null;
  }

  // Determine section type for styling
  const isVerdict = title.includes("VERDICT");
  const isAnatomy = title.includes("ANATOMY");
  const isNested = title.includes("NESTED");

  return (
    <div className={`analysis-section${isVerdict ? " analysis-section-verdict" : ""}${isAnatomy ? " analysis-section-anatomy" : ""}`}>
      <div
        className="analysis-section-header"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="analysis-step-num">{sectionIndex + 1}</span>
        <span className="analysis-section-chevron">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <span className="analysis-section-title">
          {isVerdict && "🔬 "}{isAnatomy && "🧬 "}{isNested && "🔗 "}{title}
        </span>
        <span className="analysis-section-count">{steps.length} items</span>
      </div>
      {expanded && (
        <div className="analysis-section-body">
          {filteredSteps.map(({ step, index }) => (
            <div key={index} className="analysis-entry analysis-detail">
              <DetailMessage message={step.message} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function AnalysisLog({ analysis, filename, positionDebug }: Props) {
  const [filter, setFilter] = useState("");

  if (analysis.length === 0) {
    return (
      <div className="analysis-log">
        <div className="analysis-empty">
          <p>No analysis data available.</p>
        </div>
      </div>
    );
  }

  const getIcon = (type: string) => {
    switch (type) {
      case "success":
        return <Check />;
      case "warning":
        return <AlertTriangle />;
      case "error":
        return <XCircle />;
      default:
        return <Info />;
    }
  };

  const successCount = analysis.filter((s) => s.type === "success").length;
  const warningCount = analysis.filter((s) => s.type === "warning").length;
  const errorCount = analysis.filter((s) => s.type === "error").length;
  const sectionCount = analysis.filter((s) => s.type === "section").length;

  const groups = groupAnalysisSteps(analysis);

  return (
    <div className="analysis-log">
      <div className="analysis-header">
        <h3 className="analysis-title">Parsing Analysis</h3>
        <div className="analysis-summary">
          {successCount > 0 && (
            <span className="analysis-badge analysis-badge-success">
              {successCount} OK
            </span>
          )}
          {warningCount > 0 && (
            <span className="analysis-badge analysis-badge-warning">
              {warningCount} warn
            </span>
          )}
          {errorCount > 0 && (
            <span className="analysis-badge analysis-badge-error">
              {errorCount} err
            </span>
          )}
          {sectionCount > 0 && (
            <span className="analysis-badge analysis-badge-detail">
              {sectionCount} debug
            </span>
          )}
        </div>
      </div>

      <div className="analysis-subheader">
        <span className="analysis-filename">{filename}</span>
        <span className="analysis-step-count">{analysis.length} steps</span>
      </div>

      {/* Search/filter bar */}
      {analysis.length > 15 && (
        <div className="analysis-filter-bar">
          <Search size={13} />
          <input
            type="text"
            className="analysis-filter-input"
            placeholder="Filter analysis steps..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          {filter && (
            <button
              className="analysis-filter-clear"
              onClick={() => setFilter("")}
            >
              ×
            </button>
          )}
        </div>
      )}

      <div className="analysis-entries">
        {groups.map((group, gi) => {
          if (group.kind === "section") {
            return (
              <CollapsibleSection
                key={`section-${group.sectionIndex}`}
                title={group.title}
                steps={group.steps}
                sectionIndex={group.sectionIndex}
                filter={filter}
              />
            );
          }
          // Regular step
          const { step, index } = group;
          if (filter && !step.message.toLowerCase().includes(filter.toLowerCase())) {
            return null;
          }
          return (
            <div key={index} className={`analysis-entry analysis-${step.type}`}>
              <span className="analysis-step-num">{index + 1}</span>
              <span className="analysis-icon">{getIcon(step.type)}</span>
              <span className="analysis-message">{step.message}</span>
            </div>
          );
        })}
      </div>

      {positionDebug && positionDebug.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <h3 className="analysis-title">Position Debug</h3>
          <div
            style={{
              background: "#1a1a2e",
              color: "#0f0",
              fontFamily: "Monaco, monospace",
              fontSize: 11,
              padding: 10,
              borderRadius: 4,
              maxHeight: 300,
              overflowY: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
            }}
          >
            {positionDebug.map((line, i) => (
              <div key={i}>{line}</div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
