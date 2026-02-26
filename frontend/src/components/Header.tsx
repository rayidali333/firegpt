import React from "react";
import { FileText } from "lucide-react";
import { DrawingData } from "../types";

interface Props {
  drawing: DrawingData | null;
  onReset: () => void;
}

export default function Header({ drawing, onReset }: Props) {
  return (
    <header className="header">
      <div className="header-left">
        <div className="header-logo">
          Drawing<span>IQ</span>
        </div>
        {drawing && (
          <div className="header-file">
            <FileText />
            {drawing.filename}
          </div>
        )}
      </div>
      {drawing && (
        <button className="btn-reset" onClick={onReset}>
          New Drawing
        </button>
      )}
    </header>
  );
}
