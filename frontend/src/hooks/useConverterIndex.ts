import { useEffect, useState } from "react";

import {
    ConverterIndex,
    emptyConverterIndex,
    fetchConverterIndex,
} from "../api/converters";

/**
 * Phase 5 §4.7 — fetch the converter index once at app start.
 *
 * Returns the current index (empty until the request completes) plus
 * an `isLoading` flag. The hook deliberately does not retry on failure;
 * a missing index simply means the editor offers no "insert converter"
 * suggestions, which is preferable to surfacing transient errors during
 * normal connection drag.
 */
export const useConverterIndex = (): {
    index: ConverterIndex;
    isLoading: boolean;
} => {
    const [index, setIndex] = useState<ConverterIndex>(() => emptyConverterIndex());
    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            const fetched = await fetchConverterIndex();
            if (!cancelled) {
                setIndex(fetched);
                setIsLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);

    return { index, isLoading };
};
