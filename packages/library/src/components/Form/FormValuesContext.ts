import * as React from "react";

/**
 * The form's current values, live. A Select whose options depend on a
 * sibling (`optionsFrom.dependsOn`) reads the sibling's value here and
 * narrows itself as the person types — the city list following the state.
 * Null outside any Form.
 */
export const FormValuesContext = React.createContext<Record<string, unknown> | null>(null);
