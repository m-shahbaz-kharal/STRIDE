import React from "react";

interface DashboardViewportPropertiesProps {
    viewport: { x: number; y: number; w: number; h: number; style?: Record<string, any> };
    onUpdate: (updates: { x?: number; y?: number; w?: number; h?: number; style?: Record<string, any> }) => void;
}

const DashboardViewportProperties: React.FC<DashboardViewportPropertiesProps> = ({ viewport, onUpdate }) => {

    const handleStyleChange = (key: string, value: any) => {
        onUpdate({
            style: {
                ...viewport.style,
                [key]: value
            }
        });
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        e.stopPropagation(); // Prevent keyboard shortcuts
    };

    const style = viewport.style || {};

    return (
        <div style={{ padding: '12px', height: '100%', overflowY: 'auto' }} onKeyDown={handleKeyDown}>
            {/* --- Header / Identity --- */}
            <div className="props-group" style={{ marginBottom: '16px' }}>
                <h3 style={{ margin: 0, fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>View Area</h3>
                <p style={{ margin: '4px 0 0', fontSize: '12px', color: 'var(--text-secondary)' }}>
                    Configure the main viewing area.
                </p>
            </div>

            {/* --- Layout --- */}
            <div className="props-section" style={{ marginBottom: '20px', borderTop: '1px solid var(--border-subtle)', paddingTop: '12px' }}>
                <h4 style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '10px' }}>Layout</h4>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '8px' }}>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>X (Left)</span>
                        <input
                            type="number"
                            value={String(viewport.x)}
                            onChange={(e) => onUpdate({ x: Number(e.target.value) })}
                            style={inputStyle}
                        />
                    </div>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Y (Top)</span>
                        <input
                            type="number"
                            value={String(viewport.y)}
                            onChange={(e) => onUpdate({ y: Number(e.target.value) })}
                            style={inputStyle}
                        />
                    </div>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>W (Width)</span>
                        <input
                            type="number"
                            value={String(viewport.w)}
                            onChange={(e) => onUpdate({ w: Number(e.target.value) })}
                            style={inputStyle}
                        />
                    </div>
                    <div>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>H (Height)</span>
                        <input
                            type="number"
                            value={String(viewport.h)}
                            onChange={(e) => onUpdate({ h: Number(e.target.value) })}
                            style={inputStyle}
                        />
                    </div>
                </div>
            </div>

            {/* --- Appearance --- */}
            <div className="props-section" style={{ marginBottom: '20px', borderTop: '1px solid var(--border-subtle)', paddingTop: '12px' }}>
                <h4 style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '10px' }}>Appearance</h4>

                <div style={{ marginBottom: '8px' }}>
                    <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Background Color</span>
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
                            placeholder="#ffffff"
                            style={inputStyle}
                        />
                    </div>
                </div>
            </div>
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

export default DashboardViewportProperties;
