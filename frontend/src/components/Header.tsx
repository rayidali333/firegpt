import React from "react";

export default function Header() {
  return (
    <div className="titlebar">
      <div className="titlebar-buttons">
        <span className="titlebar-btn red" />
        <span className="titlebar-btn yellow" />
        <span className="titlebar-btn green" />
      </div>
      <span className="titlebar-title">
        DrawingIQ — Fire Alarm Symbol Analysis
      </span>
    </div>
  );
}
