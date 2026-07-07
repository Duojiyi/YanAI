"use client";

import { useEffect, useRef } from "react";
import { LoaderCircle } from "lucide-react";

import webConfig from "@/constants/common-env";
import { useAuthGuard } from "@/lib/use-auth-guard";
import type { RegisterConfig } from "@/lib/api";
import { getStoredAuthKey } from "@/store/auth";

import { useSettingsStore } from "../settings/store";
import { RegisterCard } from "./components/register-card";

function readSseData(block: string) {
  return block
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim())
    .join("\n")
    .trim();
}

function RegisterDataController() {
  const didLoadRef = useRef(false);
  const loadRegister = useSettingsStore((state) => state.loadRegister);
  const setRegisterConfig = useSettingsStore((state) => state.setRegisterConfig);

  useEffect(() => {
    if (didLoadRef.current) return;
    didLoadRef.current = true;
    void loadRegister();
  }, [loadRegister]);

  useEffect(() => {
    const controller = new AbortController();
    let closed = false;

    const connect = async () => {
      const token = await getStoredAuthKey();
      if (closed || !token) {
        return;
      }
      const baseUrl = webConfig.apiUrl.replace(/\/$/, "");
      const response = await fetch(`${baseUrl}/api/register/events`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (!closed) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const blocks = buffer.split(/\r?\n\r?\n/);
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          const payload = readSseData(block);
          if (!payload || payload === "[DONE]") {
            continue;
          }
          setRegisterConfig(JSON.parse(payload) as RegisterConfig);
        }
        if (done) {
          break;
        }
      }
    };

    void connect().catch((error: unknown) => {
      if (!closed && !(error instanceof DOMException && error.name === "AbortError")) {
        console.error("register events stream failed", error);
      }
    });

    return () => {
      closed = true;
      controller.abort();
    };
  }, [setRegisterConfig]);

  return null;
}

function RegisterPageContent() {
  return (
    <>
      <RegisterDataController />
      <section className="mb-2 flex flex-col gap-1 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-1">
          <div className="text-xs font-semibold tracking-[0.18em] text-stone-500 uppercase">Register</div>
          <h1 className="text-2xl font-semibold tracking-tight">ChatGPT注册机</h1>
        </div>
      </section>
      <section>
        <RegisterCard />
      </section>
    </>
  );
}

export default function RegisterPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return <RegisterPageContent />;
}
