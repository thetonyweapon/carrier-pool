import React, { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { api, Profile } from "./api";
import { DEMO_MODE } from "./env";
import { ShellContext } from "./shell";
import { ErrorBox, isAbortError } from "./ui";

export function ProfilePage() {
  const { authBrokerId, authLoading, authError, logout } = useOutletContext<ShellContext>();
  const [profile, setProfile] = useState<Profile>();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>();
  const [message, setMessage] = useState<string>();
  const [resetOpen, setResetOpen] = useState(false);
  useEffect(() => {
    if (!authBrokerId) return;
    const controller = new AbortController();
    let current = true;
    api.me(authBrokerId, controller.signal).then((next) => {
      if (!current) return;
      setProfile(next);
      setName(next.name);
      setEmail(next.email || "");
    }).catch((nextError) => {
      if (current && !isAbortError(nextError)) setError(nextError);
    });
    return () => {
      current = false;
      controller.abort();
    };
  }, [authBrokerId]);
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(undefined);
    setMessage(undefined);
    try {
      const next = await api.updateProfile({ name, email, password: password || undefined });
      setProfile(next);
      setPassword("");
      setMessage(DEMO_MODE ? "Profile updated for this demo run." : "Profile updated.");
    } catch (nextError) {
      setError(nextError);
    }
  };
  if (authError) return <main id="main-content"><ErrorBox error={authError} /></main>;
  if (authLoading || !profile) return <main className="state" role="status">Loading profile…</main>;
  return (
    <main id="main-content" className="profile-page">
      <p className="eyebrow">ACCOUNT / PROFILE</p>
      <h1>{profile.name}</h1>
      <p>{profile.broker_name} · {profile.is_admin ? "Sysadmin" : profile.is_demo ? "Demo broker" : "Local broker"}</p>
      {Boolean(error) && <div className="state error" role="alert">{error instanceof Error ? error.message : "Could not update profile"}</div>}
      {message && <div className="state success" role="status">{message}</div>}
      <form className="profile-form" onSubmit={save}>
        <label>Name<input value={name} onChange={(event) => setName(event.target.value)} disabled={profile.profile_locked} /></label>
        <label>Email<input value={email} onChange={(event) => setEmail(event.target.value)} disabled={profile.profile_locked || profile.is_admin} /></label>
        <label>New password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={profile.profile_locked || profile.is_admin} placeholder="6-12 chars + symbol" /></label>
        <button className="primary" type="submit" disabled={profile.profile_locked}>Save changes</button>
      </form>
      {profile.profile_locked && <p className="note">{DEMO_MODE ? "Demo broker profiles are locked. Local accounts reset when the backend restarts." : "Profile changes are managed by your organization identity provider."}</p>}
      {DEMO_MODE && <button className="link-button" onClick={() => setResetOpen(true)}>Forgot password?</button>}
      <button className="logout-button" onClick={logout}>Log out</button>
      {DEMO_MODE && resetOpen && <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setResetOpen(false)}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="reset-title"><h2 id="reset-title">Password reset unavailable</h2><p>{["Email delivery is not connected in this", " demo. Create a new local account instead."].join("")}</p><button className="primary" onClick={() => setResetOpen(false)}>Close</button></div></div>}
    </main>
  );
}
