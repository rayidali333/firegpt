import React from "react";
import { Check, Info, AlertTriangle, XCircle } from "lucide-react";
import { AnalysisStep } from "../types";

interface Props {
  analysis: AnalysisStep[];
  filename: string;
}

export default function AnalysisLog({ analysis, filename }: Props) {
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
        </div>
      </div>

      <div className="analysis-subheader">
        <span className="analysis-filename">{filename}</span>
        <span className="analysis-step-count">{analysis.length} steps</span>
      </div>

      <div className="analysis-entries">
        {analysis.map((step, i) => (
          <div key={i} className={`analysis-entry analysis-${step.type}`}>
            <span className="analysis-step-num">{i + 1}</span>
            <span className="analysis-icon">{getIcon(step.type)}</span>
            <span className="analysis-message">{step.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
