import React, { useState } from "react";
import { DashboardWidget, PublishedPortData } from "../../types";

interface DashboardPropertiesProps {
    widget: DashboardWidget;
    onUpdate: (id: string, updates: Partial<DashboardWidget>) => void;
    publishedItems: { nodeId: string; nodeName: string; port: PublishedPortData }[];
}

const DashboardProperties: React.FC<DashboardPropertiesProps> = ({ widget, onUpdate, publishedItems }) => {
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

    return (
        <div style={{ padding: '12px', height: '100%', overflowY: 'auto' }} onKeyDown={handleKeyDown}>
            {/* --- Basic Identity --- */}
            <div className="props-group" style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '4px' }}>Label</label>
                <input
                    type="text"
                    value={widget.label || ""}
                    onChange={(e) => onUpdate(widget.id, { label: e.target.value })}
                    style={{ width: '100%', padding: '6px', borderRadius: '4px', border: '1px solid var(--border-input)', background: 'var(--bg-input)', color: 'var(--text-primary)' }}
                />
            </div>

            <div className="props-section" style={{ marginBottom: '20px', borderTop: '1px solid var(--border-subtle)', paddingTop: '12px' }}>
                <h4 style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '10px' }}>Layout & Layer</h4>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '8px' }}>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>X (Left)</span>
                        <input
                            type="number"
                            value={String(widget.x)}
                            onChange={(e) => onUpdate(widget.id, { x: Number(e.target.value) })}
                            style={inputStyle}
                        />
                    </div>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Y (Top)</span>
                        <input
                            type="number"
                            value={String(widget.y)}
                            onChange={(e) => onUpdate(widget.id, { y: Number(e.target.value) })}
                            style={inputStyle}
                        />
                    </div>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>W (Width)</span>
                        <input
                            type="number"
                            value={String(widget.w)}
                            onChange={(e) => onUpdate(widget.id, { w: Number(e.target.value) })}
                            style={inputStyle}
                        />
                    </div>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>H (Height)</span>
                        <input
                            type="number"
                            value={String(widget.h)}
                            onChange={(e) => onUpdate(widget.id, { h: Number(e.target.value) })}
                            style={inputStyle}
                        />
                    </div>
                </div>

                <div style={{ marginTop: '8px' }}>
                    <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Layer (Attributes)</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <div style={{ flex: 1 }}>
                            <span style={{ fontSize: '10px', color: 'var(--text-muted)', display: 'block' }}>Z-Index</span>
                            <input
                                type="number"
                                value={String(widget.zIndex ?? 0)}
                                onChange={(e) => onUpdate(widget.id, { zIndex: Number(e.target.value) })}
                                style={inputStyle}
                            />
                        </div>
                        {/* More attributes could go here */}
                    </div>
                </div>
            </div>

            {/* --- Appearance --- */}
            <div className="props-section" style={{ marginBottom: '20px', borderTop: '1px solid var(--border-subtle)', paddingTop: '12px' }}>
                <h4 style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '10px' }}>Appearance</h4>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '8px' }}>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Background</span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <input
                                type="color"
                                value={(style.backgroundColor as string) || "#ffffff"}
                                onChange={(e) => handleStyleChange('backgroundColor', e.target.value)}
                                style={{ width: '24px', height: '24px', padding: 0, border: 'none', background: 'none' }}
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
                                style={{ width: '24px', height: '24px', padding: 0, border: 'none', background: 'none' }}
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
                        <input
                            type="number"
                            value={String(parseInt(style.fontSize as string) || 14)}
                            onChange={(e) => handleStyleChange('fontSize', `${e.target.value}px`)}
                            style={inputStyle}
                        />
                    </div>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Border Radius (px)</span>
                        <input
                            type="number"
                            value={String(parseInt(style.borderRadius as string) || 4)}
                            onChange={(e) => handleStyleChange('borderRadius', `${e.target.value}px`)}
                            style={inputStyle}
                        />
                    </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '8px' }}>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Border Width (px)</span>
                        <input
                            type="number"
                            value={String(parseInt(style.borderWidth as string) || 0)}
                            onChange={(e) => handleStyleChange('borderWidth', `${e.target.value}px`)}
                            style={inputStyle}
                        />
                    </div>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Border Color</span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <input
                                type="color"
                                value={(style.borderColor as string) || "#000000"}
                                onChange={(e) => handleStyleChange('borderColor', e.target.value)}
                                style={{ width: '24px', height: '24px', padding: 0, border: 'none', background: 'none' }}
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
                    <h4 style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '10px' }}>Data Binding</h4>
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
    fontSize: '12px'
};

export default DashboardProperties;
