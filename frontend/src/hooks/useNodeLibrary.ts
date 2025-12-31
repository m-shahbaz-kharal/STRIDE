import { useCallback, useEffect, useState } from "react";
import { NodeTypeDefinition, TypeDescriptor } from "../types";

export const useNodeLibrary = () => {
    const [nodeLibrary, setNodeLibrary] = useState<NodeTypeDefinition[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const normalizeDefinition = useCallback((def: any): NodeTypeDefinition => {
        const inputs: { name: string; type: TypeDescriptor }[] =
            def.inputs ??
            (def.input_ports || []).map((name: string) => ({
                name,
                type: typeof def.input_port_types?.[name] === "object"
                    ? def.input_port_types[name]
                    : { kind: def.input_port_types?.[name] || "any" },
            }));
        const outputs: { name: string; type: TypeDescriptor }[] =
            def.outputs ??
            (def.output_ports || []).map((name: string) => ({
                name,
                type: typeof def.output_port_types?.[name] === "object"
                    ? def.output_port_types[name]
                    : { kind: def.output_port_types?.[name] || "any" },
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
                    const response = await fetch(url);
                    if (!response.ok) continue;
                    const data: any[] = await response.json();
                    setNodeLibrary(data.map((d) => normalizeDefinition(d)));
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
