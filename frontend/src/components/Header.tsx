import React from "react";

export default function Header() {
  return (
    <div className="titlebar">
      <div className="titlebar-buttons">
        <span className="titlebar-btn close" />
        <span className="titlebar-btn minimize" />
        <span className="titlebar-btn zoom" />
      </div>
      <span className="titlebar-title">FireGPT</span>
    </div>
  );
}
