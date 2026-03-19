import React from "react";
import { BookOpen, Tag, Layers, AlertTriangle, Info, CheckCircle, XCircle } from "lucide-react";
import { LegendData } from "../types";

interface Props {
  legend: LegendData;
  icons?: Record<string, string>;  // device name → SVG markup
}

export default function LegendTable({ legend, icons }: Props) {
  // Group devices by category
  const grouped: Record<string, typeof legend.devices> = {};
  for (const device of legend.devices) {
    if (!grouped[device.category]) grouped[device.category] = [];
    grouped[device.category].push(device);
  }

  const hasErrors = legend.analysis.some((s) => s.type === "error");
  const hasWarnings = legend.analysis.some((s) => s.type === "warning");

  return (
    <div className="legend-table-container">
      <div className="legend-table-header">
        <BookOpen size={16} />
        <span>
          Legend: <strong>{legend.filename}</strong>
        </span>
        <span className="legend-table-stats">
          {legend.total_device_types} device types across{" "}
          {legend.categories_found.length} categories
        </span>
      </div>

      {/* Show analysis log when there are 0 devices OR errors */}
      {(legend.devices.length === 0 || hasErrors) && legend.analysis.length > 0 && (
        <div className="legend-analysis-log">
          <div className="legend-analysis-header">
            <AlertTriangle size={14} />
            <span>
              {legend.devices.length === 0
                ? "No devices were extracted. Analysis log:"
                : "Warnings during analysis:"}
            </span>
          </div>
          <div className="legend-analysis-entries">
            {legend.analysis.map((step, i) => (
              <div key={i} className={`legend-analysis-entry legend-analysis-${step.type}`}>
                {step.type === "error" ? (
                  <XCircle size={12} />
                ) : step.type === "warning" ? (
                  <AlertTriangle size={12} />
                ) : step.type === "success" ? (
                  <CheckCircle size={12} />
                ) : (
                  <Info size={12} />
                )}
                <span>{step.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {Object.entries(grouped).map(([category, devices]) => (
        <div key={category} className="legend-category">
          <div className="legend-category-header">
            <Layers size={14} />
            <span>{category}</span>
            <span className="legend-category-count">{devices.length}</span>
          </div>
          <table className="legend-device-table">
            <thead>
              <tr>
                <th>Icon</th>
                <th>Device</th>
                <th>Abbr</th>
                <th>Symbol Description</th>
              </tr>
            </thead>
            <tbody>
              {devices.map((device, i) => (
                <tr key={i}>
                  <td className="legend-device-icon">
                    {(icons?.[device.name] || device.svg_icon) ? (
                      <span
                        className="legend-svg-icon"
                        dangerouslySetInnerHTML={{ __html: (icons?.[device.name] || device.svg_icon)! }}
                      />
                    ) : (
                      <Tag size={14} />
                    )}
                  </td>
                  <td className="legend-device-name">
                    {device.name}
                  </td>
                  <td className="legend-device-abbr">
                    {device.abbreviation || "—"}
                  </td>
                  <td className="legend-device-desc">
                    {device.symbol_description}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      {/* Always show analysis log in a collapsible section when devices exist */}
      {legend.devices.length > 0 && legend.analysis.length > 0 && (
        <details className="legend-analysis-details">
          <summary>
            Analysis Log ({legend.analysis.length} steps)
            {hasWarnings && " ⚠"}
          </summary>
          <div className="legend-analysis-entries">
            {legend.analysis.map((step, i) => (
              <div key={i} className={`legend-analysis-entry legend-analysis-${step.type}`}>
                {step.type === "error" ? (
                  <XCircle size={12} />
                ) : step.type === "warning" ? (
                  <AlertTriangle size={12} />
                ) : step.type === "success" ? (
                  <CheckCircle size={12} />
                ) : (
                  <Info size={12} />
                )}
                <span>{step.message}</span>
              </div>
            ))}
          </div>
        </details>
      )}

      {legend.notes && (
        <div className="legend-notes">
          <strong>Notes:</strong> {legend.notes}
        </div>
      )}
    </div>
  );
}
