/* Shows a short message at the bottom; `true` marks it as an error. */
export type Toast = (message: string, isError?: boolean) => void;
