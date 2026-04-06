"use client";

import { cn } from "@/lib/utils";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Download, Play, CheckCircle, Clock, AlertCircle } from "lucide-react";

interface ClipData {
  id: string;
  title: string;
  hook_score: number;
  hook_text: string;
  thumbnail_url: string;
  video_url: string;
  duration: number;
  status: string;
  created_at: string;
  published_to: Array<{ platform: string; status: string }>;
}

interface ClipCardProps {
  clip: ClipData;
}

function getHookScoreColor(score: number): string {
  if (score > 7) return "bg-green-600/20 text-green-400 border-green-800";
  if (score >= 4) return "bg-amber-600/20 text-amber-400 border-amber-800";
  return "bg-red-600/20 text-red-400 border-red-800";
}

function getStatusIcon(status: string) {
  switch (status) {
    case "published":
      return <CheckCircle className="w-4 h-4 text-green-400" />;
    case "pending":
      return <Clock className="w-4 h-4 text-amber-400 animate-pulse" />;
    case "failed":
      return <AlertCircle className="w-4 h-4 text-red-400" />;
    default:
      return null;
  }
}

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function getPlatformIcon(platform: string) {
  switch (platform.toLowerCase()) {
    case "tiktok":
      return "🎵";
    case "shorts":
    case "youtube_shorts":
      return "▶️";
    case "reels":
    case "instagram_reels":
      return "📸";
    default:
      return platform;
  }
}

export default function ClipCard({ clip }: ClipCardProps) {
  const [isHovering, setIsHovering] = useState(false);

  return (
    <div
      className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden hover:border-gray-700 transition-colors"
      onMouseEnter={() => setIsHovering(true)}
      onMouseLeave={() => setIsHovering(false)}
    >
      {/* Video Preview */}
      <div className="relative aspect-video bg-gray-800 overflow-hidden">
        {clip.thumbnail_url ? (
          <img
            src={clip.thumbnail_url}
            alt={clip.title}
            className={cn(
              "w-full h-full object-cover transition-opacity",
              isHovering ? "opacity-50" : "opacity-100"
            )}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <Play className="w-12 h-12 text-gray-600" />
          </div>
        )}

        {isHovering && clip.video_url && (
          <video
            src={clip.video_url}
            className="absolute inset-0 w-full h-full object-cover"
            muted
            loop
            autoPlay
            playsInline
          />
        )}

        {/* Hook Score Badge */}
        <Badge
          variant="outline"
          className={cn(
            "absolute top-2 right-2 font-bold text-sm",
            getHookScoreColor(clip.hook_score)
          )}
        >
          {clip.hook_score.toFixed(1)}
        </Badge>

        {/* Duration Badge */}
        <Badge
          variant="secondary"
          className="absolute bottom-2 right-2 text-xs"
        >
          {formatDuration(clip.duration)}
        </Badge>

        {/* Play Overlay */}
        {isHovering && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="bg-black/40 rounded-full p-3">
              <Play className="w-6 h-6 text-white fill-white" />
            </div>
          </div>
        )}
      </div>

      {/* Content */}
      <div className="p-4 space-y-3">
        <h3 className="font-semibold text-sm truncate">{clip.title}</h3>

        {clip.hook_text && (
          <p className="text-xs text-gray-400 line-clamp-2 italic">
            &ldquo;{clip.hook_text}&rdquo;
          </p>
        )}

        {/* Platform Publish Status */}
        {clip.published_to && clip.published_to.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {clip.published_to.map((pub) => (
              <div
                key={pub.platform}
                className="flex items-center gap-1 text-xs px-2 py-1 bg-gray-800 rounded-md"
              >
                <span>{getPlatformIcon(pub.platform)}</span>
                {getStatusIcon(pub.status)}
                <span className="text-gray-400 capitalize">
                  {pub.platform.replace("_", " ")}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2 pt-1">
          {clip.video_url && (
            <Button
              variant="outline"
              size="sm"
              className="flex-1 text-xs"
              onClick={() => window.open(clip.video_url, "_blank")}
            >
              <Download className="w-3.5 h-3.5 mr-1" />
              Download
            </Button>
          )}
        </div>

        <div className="text-xs text-gray-600">
          {new Date(clip.created_at).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
            year: "numeric",
          })}
        </div>
      </div>
    </div>
  );
}
