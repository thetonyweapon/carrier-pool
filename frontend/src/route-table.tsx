import { Navigate, Route, Routes } from "react-router-dom";
import { DetailPage } from "./detail";
import { LoginPage } from "./login";
import { ProfilePage } from "./profile";
import { Queue } from "./queue";
import { Shell } from "./shell";

export function RouteTable() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/brokers" element={<Navigate to="/login" replace />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/brokers/:brokerId/loads" element={<Queue />} />
        <Route path="/brokers/:brokerId/loads/:loadId" element={<DetailPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Route>
    </Routes>
  );
}
