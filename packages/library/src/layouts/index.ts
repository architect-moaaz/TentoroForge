// Static JSON imports — resolveJsonModule enabled in tsconfig.json
import dashboard from "./DashboardLayout.json";
import auth from "./AuthLayout.json";
import marketing from "./MarketingLayout.json";
import settings from "./SettingsLayout.json";

export const layouts = {
  DashboardLayout: dashboard,
  AuthLayout: auth,
  MarketingLayout: marketing,
  SettingsLayout: settings,
} as const;
