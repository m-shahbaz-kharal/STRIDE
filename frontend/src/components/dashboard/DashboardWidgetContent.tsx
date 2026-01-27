import React from "react";
import { DashboardWidget, BlueprintNodeData } from "../../types";
import { Node } from "reactflow";

interface DashboardWidgetContentProps {
    widget: DashboardWidget;
    mode: "design" | "view";
    nodes: Node<BlueprintNodeData>[];
    outputs: Record<string, unknown>;
    editingWidgetId: string | null;
    onUpdateWidget: (id: string, updates: Partial<DashboardWidget>) => void;
    setEditingWidgetId: (id: string | null) => void;
    onInputChange?: (nodeId: string, portName: string, value: any) => void;
}

export const DashboardWidgetContent: React.FC<DashboardWidgetContentProps> = ({
    widget,
    mode,
    nodes,
    outputs,
    editingWidgetId,
    onUpdateWidget,
    setEditingWidgetId,
    onInputChange
}) => {
    const isEditing = editingWidgetId === widget.id;

    const handleLabelChange = (newLabel: string) => {
        onUpdateWidget(widget.id, { label: newLabel });
    };

    const handleLabelBlur = () => {
        setEditingWidgetId(null);
    };

    const handleLabelKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter') {
            setEditingWidgetId(null);
        }
        e.stopPropagation();
    };

    // Find bound node/value if applicable
    let value: any = null;
    if (widget.nodeId && widget.portName) {
        // 1. Try outputs prop
        if (outputs[widget.nodeId] && (outputs[widget.nodeId] as Record<string, any>)[widget.portName] !== undefined) {
            value = (outputs[widget.nodeId] as Record<string, any>)[widget.portName];
        } else {
            // 2. Try node cached last_outputs
            const node = nodes.find(n => n.id === widget.nodeId);
            if (node?.data.last_outputs) {
                value = node.data.last_outputs[widget.portName];
            }
            // 3. Try node inputs if it's an input widget
            if (node && node.data.inputValues && node.data.inputValues[widget.portName] !== undefined && widget.type === 'bound-input') {
                value = node.data.inputValues[widget.portName];
            }
        }
    }

    switch (widget.type) {
        case "label":
            if (isEditing) {
                return (
                    <input
                        autoFocus
                        type="text"
                        value={widget.label || ""}
                        onChange={(e) => handleLabelChange(e.target.value)}
                        onBlur={handleLabelBlur}
                        onKeyDown={handleLabelKeyDown}
                        onPointerDown={e => e.stopPropagation()}
                        style={{
                            width: '100%', height: '100%',
                            border: 'none', background: 'transparent',
                            fontSize: 'inherit', fontWeight: 'inherit', color: 'inherit',
                            outline: 'none'
                        }}
                    />
                );
            }
            return <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center' }}>{widget.label || "Label"}</div>;
        case "container":
            return <div style={{ width: '100%', height: '100%', border: '1px dashed var(--border-subtle)', borderRadius: '4px' }}></div>;
        case "panel":
            return <div style={{ width: '100%', height: '100%', background: 'var(--bg-surface)', borderRadius: '4px', boxShadow: '0 2px 4px rgba(0,0,0,0.2)' }}></div>;
        case "bound-output":
            if (typeof value === "string" && (value.startsWith("data:image") || value.startsWith("http"))) {
                return <img src={value} alt="output" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />;
            } else if (value && typeof value === 'object' && (value as any)._type === 'StreamResource') {
                const stream = value as any;
                return (
                    <div style={{ width: '100%', height: '100%', position: 'relative', background: '#000' }}>
                        <img src={`/api/streams/${stream.stream_id}/frame?ts=${Date.now()}`} alt="stream" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
                    </div>
                );
            }
            return (
                <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>
                    {widget.label && <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>{widget.label}</div>}
                    <div style={{ flex: 1, background: 'var(--bg-tertiary)', padding: '8px', borderRadius: '4px', overflow: 'auto', fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
                        {value !== undefined ? (typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)) : <span style={{ opacity: 0.5 }}>No Data</span>}
                    </div>
                </div>
            );
        case "bound-input":
            return (
                <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>
                    {widget.label && <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>{widget.label}</div>}
                    {widget.inputType === 'boolean' ? (
                        <div style={{ flex: 1, display: 'flex', alignItems: 'center' }}>
                            <input
                                type="checkbox"
                                checked={!!value}
                                onChange={(e) => onInputChange?.(widget.nodeId!, widget.portName!, e.target.checked)}
                                onPointerDown={e => e.stopPropagation()}
                                style={{ width: '20px', height: '20px', accentColor: 'var(--primary-color)' }}
                            />
                            <span style={{ marginLeft: '8px', fontSize: '12px', color: 'var(--text-primary)' }}>{value ? 'True' : 'False'}</span>
                        </div>
                    ) : (widget.inputType === 'int' || widget.inputType === 'float') ? (
                        <input
                            type="number"
                            value={value ?? ""}
                            step={widget.inputType === 'float' ? "any" : "1"}
                            onChange={(e) => {
                                const val = e.target.value;
                                if (val === "") {
                                    onInputChange?.(widget.nodeId!, widget.portName!, null);
                                } else {
                                    onInputChange?.(widget.nodeId!, widget.portName!, widget.inputType === 'int' ? parseInt(val) : parseFloat(val));
                                }
                            }}
                            onPointerDown={e => e.stopPropagation()}
                            style={{
                                width: '100%', padding: '8px', background: 'var(--bg-input)', border: '1px solid var(--border-input)', borderRadius: '4px', color: 'var(--text-primary)'
                            }}
                        />
                    ) : (
                        <input
                            type="text"
                            value={value ?? ""}
                            onChange={(e) => onInputChange?.(widget.nodeId!, widget.portName!, e.target.value)}
                            onPointerDown={e => e.stopPropagation()}
                            style={{
                                width: '100%', padding: '8px', background: 'var(--bg-input)', border: '1px solid var(--border-input)', borderRadius: '4px', color: 'var(--text-primary)'
                            }}
                        />
                    )}
                </div>
            );
        default:
            return <div>Unknown Widget</div>;
    }
};
