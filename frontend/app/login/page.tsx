"use client";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { LoginView } from "@/components/login-view";

function LoginFromParams() {
  const params = useSearchParams();
  return <LoginView error={params.get("error")} next={params.get("next")} />;
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginFromParams />
    </Suspense>
  );
}
