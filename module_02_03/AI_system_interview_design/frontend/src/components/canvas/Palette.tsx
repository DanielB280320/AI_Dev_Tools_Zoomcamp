import { COMPONENT_LIBRARY } from "@/lib/canvas-types";

export function Palette({ disabled }: { disabled: boolean }) {
  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3">
      <div className="label-caps">Components</div>
      <div className="grid grid-cols-2 gap-2">
        {COMPONENT_LIBRARY.map((c) => (
          <button
            key={c.kind}
            type="button"
            draggable={!disabled}
            onDragStart={(e) => {
              e.dataTransfer.setData("application/x-sdi-component", c.kind);
              e.dataTransfer.effectAllowed = "copy";
            }}
            disabled={disabled}
            className="group flex cursor-grab flex-col gap-2 rounded-md border border-border bg-surface-2 p-2 text-left text-xs leading-tight transition-colors hover:border-primary disabled:cursor-not-allowed disabled:opacity-50"
            title={`Drag "${c.label}" onto the canvas`}
          >
            <span
              className="h-1.5 w-8 rounded-full"
              style={{ backgroundColor: `var(--accent-${c.accent})` }}
            />
            <span className="text-foreground">{c.label}</span>
          </button>
        ))}
      </div>
      <p className="mt-auto text-xs text-muted-foreground">
        Drag a block onto the board. Double-click any block to rename it.
      </p>
    </div>
  );
}
