import React from "react";
import { BookOpen, Tag, Layers } from "lucide-react";
import { LegendData } from "../types";

interface Props {
  legend: LegendData;
}

export default function LegendTable({ legend }: Props) {
  // Group devices by category
  const grouped: Record<string, typeof legend.devices> = {};
  for (const device of legend.devices) {
    if (!grouped[device.category]) grouped[device.category] = [];
    grouped[device.category].push(device);
  }

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
                <th>Device</th>
                <th>Abbr</th>
                <th>Symbol Description</th>
              </tr>
            </thead>
            <tbody>
              {devices.map((device, i) => (
                <tr key={i}>
                  <td className="legend-device-name">
                    <Tag size={12} />
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

      {legend.notes && (
        <div className="legend-notes">
          <strong>Notes:</strong> {legend.notes}
        </div>
      )}
    </div>
  );
}
