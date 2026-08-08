import { demoModeFromEnv } from "./oidc";

export const DEMO_MODE = demoModeFromEnv(import.meta.env.VITE_DEMO_MODE);
export const AUTH_LOGIN_URL = import.meta.env.VITE_AUTH_LOGIN_URL as string | undefined;
export const DEMO_LABEL = ["DEMO", "MODE"].join(" ");
export const AUTH_CLIENT_ID = import.meta.env.VITE_AUTH_CLIENT_ID as string | undefined;
export const AUTH_REDIRECT_URI = import.meta.env.VITE_AUTH_REDIRECT_URI as string | undefined;
