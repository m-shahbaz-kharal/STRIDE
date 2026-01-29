import React, { useState } from "react";
import { DashboardWidget, PublishedPortData } from "../../types";

interface DashboardPropertiesProps {
    widget: DashboardWidget;
    onUpdate: (id: string, updates: Partial<DashboardWidget>) => void;
    publishedItems: { nodeId: string; nodeName: string; port: PublishedPortData }[];
    value?: any;
    onInputChange?: (nodeId: string, portName: string, value: any) => void;
}

const NumberInput = ({ value, onChange, placeholder, style }: { value: number | string, onChange: (val: number) => void, placeholder?: string, style?: React.CSSProperties }) => {
    // Determine step based on value magnitude or type? Default to 1.
    const step = 1;

    const handleWheel = (e: React.WheelEvent<HTMLInputElement>) => {
        // Only if focused? User said "selected". Standard behavior is focus.
        // We'll enforce focus requirement implicitly or explicitly.
        // Chrome handles this natively if type=number.
        // But we want to ensure it works and potentially prevent page scroll.
        if (document.activeElement === e.currentTarget) {
            e.preventDefault();
            e.stopPropagation();

            const delta = e.deltaY > 0 ? -1 : 1;
            const mult = e.shiftKey ? 10 : 1;
            const currentVal = Number(value) || 0;
            onChange(currentVal + (delta * step * mult));
        }
    };

    return (
        <input
            type="number"
            value={value}
            onChange={(e) => onChange(Number(e.target.value))}
            onWheel={handleWheel}
            placeholder={placeholder}
            style={{
                ...inputStyle,
                ...style
            }}
            className="property-number-input"
        />
    );
};

const DashboardProperties: React.FC<DashboardPropertiesProps> = ({ widget, onUpdate, publishedItems, value, onInputChange }) => {
    // ... (rest of implementation) ...

    const handleStyleChange = (key: string, value: any) => {
        onUpdate(widget.id, {
            style: {
                ...widget.style,
                [key]: value
            }
        });
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        e.stopPropagation(); // Prevent keyboard shortcuts
    };

    const style = widget.style || {};
    const showText = widget.type !== 'panel' && widget.id !== 'view-bounds';

    return (
        <div style={{ padding: '12px', height: '100%', overflowY: 'auto' }} onKeyDown={handleKeyDown}>
            {/* Global Styles for Inputs to match theme */}
            <style>{`
                .property-number-input:focus {
                    border-color: var(--accent-primary) !important;
                    outline: none;
                    box-shadow: 0 0 0 1px var(--accent-primary);
                }
                /* Hide spinners for Chrome, Safari, Edge, Opera */
                .property-number-input::-webkit-outer-spin-button,
                .property-number-input::-webkit-inner-spin-button {
                    -webkit-appearance: none;
                    margin: 0;
                }
                /* Hide spinners for Firefox */
                .property-number-input {
                    -moz-appearance: textfield;
                }
            `}</style>

            {/* --- Basic Identity --- */}
            {showText && (
                <div className="props-group" style={{ marginBottom: '16px' }}>
                    <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '4px' }}>Text</label>
                    {widget.type === 'bound-input' ? (
                        widget.inputType === 'int' || widget.inputType === 'float' ? (
                            <NumberInput
                                value={value !== undefined && value !== null ? Number(value) : ""}
                                onChange={(val) => {
                                    if (widget.nodeId && widget.portName && onInputChange) {
                                        onInputChange(widget.nodeId, widget.portName, val);
                                    }
                                }}
                            />
                        ) : (
                            <input
                                type="text"
                                value={value !== undefined && value !== null ? String(value) : ""}
                                onChange={(e) => {
                                    if (widget.nodeId && widget.portName && onInputChange) {
                                        onInputChange(widget.nodeId, widget.portName, e.target.value);
                                    }
                                }}
                                style={inputStyle}
                            />
                        )
                    ) : (
                        <input
                            type="text"
                            value={widget.label || ""}
                            onChange={(e) => onUpdate(widget.id, { label: e.target.value })}
                            style={inputStyle}
                        />
                    )}
                </div>
            )}

            <div className="props-section" style={{ marginBottom: '20px', borderTop: showText ? '1px solid var(--border-subtle)' : 'none', paddingTop: showText ? '12px' : '0' }}>
                <h4 style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '10px', marginTop: 0 }}>Layout & Layer</h4>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '8px' }}>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>X (Left)</span>
                        <NumberInput
                            value={String(widget.x)}
                            onChange={(val) => onUpdate(widget.id, { x: val })}
                        />
                    </div>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Y (Top)</span>
                        <NumberInput
                            value={String(widget.y)}
                            onChange={(val) => onUpdate(widget.id, { y: val })}
                        />
                    </div>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>W (Width)</span>
                        <NumberInput
                            value={String(widget.w)}
                            onChange={(val) => onUpdate(widget.id, { w: val })}
                        />
                    </div>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>H (Height)</span>
                        <NumberInput
                            value={String(widget.h)}
                            onChange={(val) => onUpdate(widget.id, { h: val })}
                        />
                    </div>
                </div>

                <div style={{ marginTop: '8px' }}>
                    <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Layer (Attributes)</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <div style={{ flex: 1 }}>
                            <span style={{ fontSize: '10px', color: 'var(--text-muted)', display: 'block' }}>Z-Index</span>
                            <NumberInput
                                value={String(widget.zIndex ?? 0)}
                                onChange={(val) => onUpdate(widget.id, { zIndex: val })}
                            />
                        </div>
                    </div>
                </div>
            </div>

            {/* --- Appearance --- */}
            <div className="props-section" style={{ marginBottom: '20px', borderTop: '1px solid var(--border-subtle)', paddingTop: '12px' }}>
                <h4 style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '10px', marginTop: 0 }}>Appearance</h4>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '8px' }}>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Background</span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <input
                                type="color"
                                value={(style.backgroundColor as string) || "#ffffff"}
                                onChange={(e) => handleStyleChange('backgroundColor', e.target.value)}
                                style={{ width: '24px', height: '24px', padding: 0, border: 'none', background: 'none', cursor: 'pointer' }}
                            />
                            <input
                                type="text"
                                value={(style.backgroundColor as string) || ""}
                                onChange={(e) => handleStyleChange('backgroundColor', e.target.value)}
                                placeholder="transparent"
                                style={inputStyle}
                            />
                        </div>
                    </div>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Text Color</span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <input
                                type="color"
                                value={(style.color as string) || "#000000"}
                                onChange={(e) => handleStyleChange('color', e.target.value)}
                                style={{ width: '24px', height: '24px', padding: 0, border: 'none', background: 'none', cursor: 'pointer' }}
                            />
                            <input
                                type="text"
                                value={(style.color as string) || ""}
                                onChange={(e) => handleStyleChange('color', e.target.value)}
                                placeholder="inherit"
                                style={inputStyle}
                            />
                        </div>
                    </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '8px' }}>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Font Size (px)</span>
                        <NumberInput
                            value={String(parseInt(style.fontSize as string) || 14)}
                            onChange={(val) => handleStyleChange('fontSize', `${val}px`)}
                        />
                    </div>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Border Radius (px)</span>
                        <NumberInput
                            value={String(parseInt(style.borderRadius as string) || 4)}
                            onChange={(val) => handleStyleChange('borderRadius', `${val}px`)}
                        />
                    </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '8px' }}>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Border Width (px)</span>
                        <NumberInput
                            value={String(parseInt(style.borderWidth as string) || 0)}
                            onChange={(val) => handleStyleChange('borderWidth', `${val}px`)}
                        />
                    </div>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Border Color</span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <input
                                type="color"
                                value={(style.borderColor as string) || "#000000"}
                                onChange={(e) => handleStyleChange('borderColor', e.target.value)}
                                style={{ width: '24px', height: '24px', padding: 0, border: 'none', background: 'none', cursor: 'pointer' }}
                            />
                        </div>
                    </div>
                </div>

                <div style={{ marginTop: '8px' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: 'var(--text-primary)' }}>
                        <input
                            type="checkbox"
                            checked={!!style.boxShadow}
                            onChange={(e) => handleStyleChange('boxShadow', e.target.checked ? '0 4px 6px rgba(0,0,0,0.1)' : undefined)}
                        />
                        Enable Shadow
                    </label>
                </div>
            </div>


            {/* --- Binding (Only for bound widgets) --- */}
            {(widget.type === 'bound-input' || widget.type === 'bound-output') && (
                <div className="props-section" style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '12px' }}>
                    <h4 style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '10px', marginTop: 0 }}>Data Binding</h4>
                    <div style={{ padding: '8px', background: 'var(--bg-tertiary)', borderRadius: '4px', fontSize: '11px', fontFamily: 'monospace' }}>
                        <div style={{ marginBottom: '4px' }}>Node: <span style={{ color: 'var(--accent-primary)' }}>{widget.nodeId}</span></div>
                        <div>Port: <span style={{ color: 'var(--accent-secondary)' }}>{widget.portName}</span></div>
                    </div>
                </div>
            )}
        </div>
    );
};

const inputStyle = {
    width: '100%',
    padding: '4px 6px',
    background: 'var(--bg-input)',
    border: '1px solid var(--border-input)',
    borderRadius: '4px',
    color: 'var(--text-primary)',
    fontSize: '12px',
    boxSizing: 'border-box' as const
};

export default DashboardProperties;
