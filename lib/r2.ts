/**
 * Cloudflare R2 client — S3-compatible via @aws-sdk/client-s3
 *
 * Variables required:
 *   R2_ACCOUNT_ID        — found in Cloudflare dashboard → R2 → Overview
 *   R2_ACCESS_KEY_ID     — R2 → Manage API Tokens
 *   R2_SECRET_ACCESS_KEY — idem
 *   R2_BUCKET_NAME       — name of your R2 bucket (e.g. "affili-compare-images")
 *   R2_PUBLIC_URL        — public URL prefix (e.g. "https://images.yourdomain.com")
 *
 * IAM policy required on the R2 API token:
 *   {"effect":"allow","resources":["com.cloudflare.edge.r2.bucket.<ACCOUNT_ID>_default_<BUCKET_NAME>"],"permission_groups":[{"id":"...","name":"Workers R2 Storage Object Write"}]}
 */

import {
  S3Client,
  PutObjectCommand,
  DeleteObjectCommand,
  HeadObjectCommand,
} from "@aws-sdk/client-s3";

if (
  !process.env.R2_ACCOUNT_ID ||
  !process.env.R2_ACCESS_KEY_ID ||
  !process.env.R2_SECRET_ACCESS_KEY ||
  !process.env.R2_BUCKET_NAME
) {
  // Only throw at runtime (not during build if vars are missing)
  if (process.env.NODE_ENV === "production") {
    throw new Error("Missing R2 environment variables");
  }
}

export const r2Client = new S3Client({
  region: "auto",
  endpoint: `https://${process.env.R2_ACCOUNT_ID}.r2.cloudflarestorage.com`,
  credentials: {
    accessKeyId: process.env.R2_ACCESS_KEY_ID ?? "",
    secretAccessKey: process.env.R2_SECRET_ACCESS_KEY ?? "",
  },
});

const BUCKET = process.env.R2_BUCKET_NAME ?? "";
const PUBLIC_URL = (process.env.R2_PUBLIC_URL ?? "").replace(/\/$/, "");

/**
 * Upload a Buffer or Uint8Array to R2.
 * @param key       — object key, e.g. "pins/aspirateurs-sans-fil-2024.jpg"
 * @param body      — file content as Buffer
 * @param mimeType  — e.g. "image/jpeg" or "image/png"
 * @returns public URL of the uploaded object
 */
export async function uploadToR2(
  key: string,
  body: Buffer | Uint8Array,
  mimeType: string = "image/jpeg"
): Promise<string> {
  await r2Client.send(
    new PutObjectCommand({
      Bucket: BUCKET,
      Key: key,
      Body: body,
      ContentType: mimeType,
      // Cache aggressively for images (30 days)
      CacheControl: "public, max-age=2592000, immutable",
    })
  );

  return `${PUBLIC_URL}/${key}`;
}

/**
 * Delete an object from R2 by key.
 */
export async function deleteFromR2(key: string): Promise<void> {
  await r2Client.send(
    new DeleteObjectCommand({
      Bucket: BUCKET,
      Key: key,
    })
  );
}

/**
 * Check if an object already exists in R2 (avoids redundant uploads).
 */
export async function existsInR2(key: string): Promise<boolean> {
  try {
    await r2Client.send(
      new HeadObjectCommand({
        Bucket: BUCKET,
        Key: key,
      })
    );
    return true;
  } catch {
    return false;
  }
}

/**
 * Build the public URL for a key without checking existence.
 */
export function getR2Url(key: string): string {
  return `${PUBLIC_URL}/${key}`;
}

/**
 * Build a canonical R2 key for a Pinterest pin image.
 * Format: pins/{category-slug}/{comparison-slug}-{YYYYMM}.jpg
 */
export function buildPinKey(
  categorySlug: string,
  comparisonSlug: string
): string {
  const now = new Date();
  const ym = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}`;
  return `pins/${categorySlug}/${comparisonSlug}-${ym}.jpg`;
}
