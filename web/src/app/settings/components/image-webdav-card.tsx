"use client";

import { CloudUpload, LoaderCircle, Settings } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { WebDAVSettingsDialog } from "@/components/webdav-settings-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  fetchImagesWebDAVConfig,
  updateImagesWebDAVConfig,
  type ImageWebDAVConfig,
  type ImageWebDAVConfigPayload,
} from "@/lib/api";

export function ImageWebDAVCard() {
  const [config, setConfig] = useState<ImageWebDAVConfig | null>(null);
  const [open, setOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  const loadConfig = async () => {
    setIsLoading(true);
    try {
      const data = await fetchImagesWebDAVConfig();
      setConfig(data.webdav);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载 WebDAV 配置失败");
    } finally {
      setIsLoading(false);
    }
  };

  const saveConfig = async (payload: ImageWebDAVConfigPayload) => {
    setIsSaving(true);
    try {
      const data = await updateImagesWebDAVConfig(payload);
      setConfig(data.webdav);
      setOpen(false);
      toast.success("WebDAV 配置已保存");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存 WebDAV 配置失败");
    } finally {
      setIsSaving(false);
    }
  };

  useEffect(() => {
    void loadConfig();
  }, []);

  const enabled = Boolean(config?.enabled);
  const destination = config?.public_url || config?.url || "未配置";

  return (
    <>
      <Card className="rounded-lg border-white/80 bg-white/80 shadow-sm">
        <CardContent className="flex flex-col gap-4 p-6 md:flex-row md:items-center md:justify-between">
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-sm font-semibold text-stone-900">
              <CloudUpload className="size-4 text-stone-500" />
              图片 WebDAV 存储
            </div>
            {isLoading ? (
              <div className="flex items-center gap-2 text-sm text-stone-500">
                <LoaderCircle className="size-4 animate-spin" />
                加载中
              </div>
            ) : (
              <div className="space-y-1 text-sm text-stone-600">
                <div>{enabled ? "已启用自动保存" : "未启用自动保存"}</div>
                <div className="break-all text-xs text-stone-500">{destination}</div>
              </div>
            )}
          </div>
          <Button
            type="button"
            variant="outline"
            className="h-10 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
            onClick={() => setOpen(true)}
            disabled={isLoading}
          >
            <Settings className="size-4" />
            配置
          </Button>
        </CardContent>
      </Card>
      <WebDAVSettingsDialog
        open={open}
        onOpenChange={setOpen}
        config={config}
        isSaving={isSaving}
        title="图片 WebDAV 存储"
        description="启用后，新生成图片会自动上传到 WebDAV；配置公开访问前缀后，图片接口优先返回远程 URL。"
        onSave={saveConfig}
      />
    </>
  );
}
