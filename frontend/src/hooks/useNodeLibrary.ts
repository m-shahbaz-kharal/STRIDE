import { useCallback, useEffect, useState } from "react";
import { authFetch } from "../api";
import { NodeTypeDefinition, TypeDescriptor } from "../types";

export const useNodeLibrary = () => {
    const [nodeLibrary, setNodeLibrary] = useState<NodeTypeDefinition[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const normalizeDefinition = useCallback((def: any): NodeTypeDefinition => {
        const coerceType = (raw: any): TypeDescriptor => {
            if (!raw) return { kind: "any" };
            if (typeof raw === "string") return { kind: raw as TypeDescriptor["kind"] };
            const normalized: TypeDescriptor & Record<string, unknown> = { ...raw } as TypeDescriptor;
            const elementType = (normalized as any).elementType ?? (normalized as any).element_type;
            const normalizedElement = elementType ? coerceType(elementType) : undefined;
            if (normalized.kind === "map") {
                if (normalizedElement && !normalized.value) {
                    normalized.value = normalizedElement as TypeDescriptor;
                }
                if (!normalized.value && normalized.item) {
                    normalized.value = normalized.item;
                }
            } else if (normalizedElement && !normalized.item) {
                normalized.item = normalizedElement as TypeDescriptor;
            }
            if (normalized.item && typeof normalized.item === "object") {
                normalized.item = coerceType(normalized.item);
            }
            if (normalized.value && typeof normalized.value === "object") {
                normalized.value = coerceType(normalized.value);
            }
            if (normalized.fields) {
                normalized.fields = Object.fromEntries(
                    Object.entries(normalized.fields).map(([key, value]) => [key, coerceType(value)])
                );
            }
            return normalized;
        };

        const inputs: { name: string; type: TypeDescriptor }[] =
            def.inputs ??
            (def.input_ports || []).map((name: string) => ({
                name,
                type: coerceType(def.input_port_types?.[name]),
            }));
        const outputs: { name: string; type: TypeDescriptor }[] =
            def.outputs ??
            (def.output_ports || []).map((name: string) => ({
                name,
                type: coerceType(def.output_port_types?.[name]),
            }));

        return {
            ...def,
            inputs,
            outputs,
            input_ports: inputs.map((p) => p.name),
            output_ports: outputs.map((p) => p.name),
            input_port_types: Object.fromEntries(inputs.map((p) => [p.name, p.type])),
            output_port_types: Object.fromEntries(outputs.map((p) => [p.name, p.type])),
        };
    }, []);

    // Load node types on mount
    useEffect(() => {
        const load = async () => {
            setIsLoading(true);
            setError(null);
            const urls = ["/api/node-definitions", "/api/node-types"];
            for (const url of urls) {
                try {
                    const response = await authFetch(url);
                    if (!response.ok) continue;
                    const data: any[] = await response.json();
                    setNodeLibrary(data.filter((d) => d.node_type !== "general.to_display").map((d) => normalizeDefinition(d)));
                    setIsLoading(false);
                    return;
                } catch (err) {
                    continue;
                }
            }
            setNodeLibrary([]);
            setIsLoading(false);
            setError("Failed to load node types");
        };
        load();
    }, [normalizeDefinition]);

    return {
        nodeLibrary,
        isLoading,
        error,
        normalizeDefinition,
    };
};
