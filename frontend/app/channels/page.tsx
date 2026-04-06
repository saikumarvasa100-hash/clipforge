"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Upload,
  Power,
  Link as LinkIcon,
  Loader2,
  Trash2,
  RotateCcw,
} from "lucide-react";
import { supabase } from "@/lib/supabase";

interface YouTubeChannel {
  id: string;
  channel_name: string;
  channel_id: string;
  avatar_url: string;
  subscriber_count: number;
  last_synced: string | null;
  auto_process: boolean;
  access_token: string;
  refresh_token: string;
}

export default function ChannelsPage() {
  const [channels, setChannels] = useState<YouTubeChannel[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);

  useEffect(() => {
    fetchChannels();
  }, []);

  async function fetchChannels() {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) return;

      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/channels`,
        {
          headers: { Authorization: `Bearer ${session.access_token}` },
        }
      );
      if (res.ok) {
        const data = await res.json();
        setChannels(data);
      }
    } catch (error) {
      console.error("Failed to fetch channels:", error);
    } finally {
      setLoading(false);
    }
  }

  async function handleConnectYouTube() {
    setConnecting(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) {
        window.location.href = "/login";
        return;
      }

      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/channels/youtube/connect`,
        {
          headers: { Authorization: `Bearer ${session.access_token}` },
        }
      );
      const data = await res.json();
      if (data.auth_url) {
        window.location.href = data.auth_url;
      }
    } catch (error) {
      console.error("Connection failed:", error);
    } finally {
      setConnecting(false);
    }
  }

  async function handleSync(channelId: string) {
    setSyncing(channelId);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) return;

      await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/channels/${channelId}/sync`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${session.access_token}`,
            "Content-Type": "application/json",
          },
        }
      );
    } catch (error) {
      console.error("Sync failed:", error);
    } finally {
      setSyncing(null);
    }
  }

  async function handleToggleAutoProcess(channelId: string, current: boolean) {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) return;

      await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/channels/${channelId}/auto-process`,
        {
          method: "PATCH",
          headers: {
            Authorization: `Bearer ${session.access_token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ auto_process: !current }),
        }
      );
      setChannels((prev) =>
        prev.map((ch) =>
          ch.id === channelId
            ? { ...ch, auto_process: !current }
            : ch
        )
      );
    } catch (error) {
      console.error("Toggle failed:", error);
    }
  }

  async function handleDisconnect(channelId: string) {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) return;

      await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/channels/${channelId}`,
        {
          method: "DELETE",
          headers: { Authorization: `Bearer ${session.access_token}` },
        }
      );
      setChannels((prev) => prev.filter((ch) => ch.id !== channelId));
    } catch (error) {
      console.error("Disconnect failed:", error);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-8 h-8 text-violet-400 animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold mb-2">Channels</h1>
          <p className="text-gray-400">
            Manage your connected YouTube channels and sync settings.
          </p>
        </div>
        <Button
          onClick={handleConnectYouTube}
          disabled={connecting}
          className="bg-red-600 hover:bg-red-700 gap-2"
        >
          {connecting ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <LinkIcon className="w-4 h-4" />
          )}
          Connect YouTube Channel
        </Button>
      </div>

      {channels.length === 0 ? (
        <Card className="bg-gray-900 border-gray-800">
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <Upload className="w-12 h-12 text-gray-700 mb-4" />
            <h3 className="text-lg font-semibold mb-2">No channels connected</h3>
            <p className="text-gray-500 max-w-md mb-6">
              Connect your YouTube channel to let ClipForge automatically
              detect viral moments in your videos.
            </p>
            <Button
              onClick={handleConnectYouTube}
              disabled={connecting}
              className="bg-red-600 hover:bg-red-700 gap-2"
            >
              <LinkIcon className="w-4 h-4" />
              Connect with Google
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {channels.map((channel) => (
            <Card key={channel.id} className="bg-gray-900 border-gray-800">
              <CardHeader className="flex flex-row items-center gap-4">
                {channel.avatar_url ? (
                  <img
                    src={channel.avatar_url}
                    alt={channel.channel_name}
                    className="w-12 h-12 rounded-full"
                  />
                ) : (
                  <div className="w-12 h-12 rounded-full bg-gray-700 flex items-center justify-center">
                    <Upload className="w-6 h-6 text-gray-400" />
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <h3 className="font-semibold truncate">
                    {channel.channel_name}
                  </h3>
                  <p className="text-sm text-gray-500">
                    {channel.subscriber_count.toLocaleString()} subscribers
                  </p>
                </div>
                <Badge variant="outline" className="text-green-400 border-green-800">
                  Connected
                </Badge>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="text-xs text-gray-500">
                  {channel.last_synced
                    ? `Last synced: ${new Date(channel.last_synced).toLocaleDateString()}`
                    : "Never synced"}
                </div>

                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-400">Auto-processing</span>
                  <Switch
                    checked={channel.auto_process}
                    onCheckedChange={() =>
                      handleToggleAutoProcess(channel.id, channel.auto_process)
                    }
                  />
                </div>

                <div className="flex gap-2">
                  <Button
                    onClick={() => handleSync(channel.id)}
                    disabled={syncing === channel.id}
                    variant="outline"
                    size="sm"
                    className="flex-1"
                  >
                    {syncing === channel.id ? (
                      <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                    ) : (
                      <RotateCcw className="w-4 h-4 mr-1" />
                    )}
                    Sync Now
                  </Button>
                  <Button
                    onClick={() => handleDisconnect(channel.id)}
                    variant="outline"
                    size="sm"
                    className="text-red-400 hover:text-red-300 hover:bg-red-950"
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
