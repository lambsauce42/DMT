#!/usr/bin/env bash
set -euo pipefail

parts_dir="vendor/whisper.cpp/models/ggml-base.en.bin.xz.parts"
xz_path="vendor/whisper.cpp/models/ggml-base.en.bin.xz"
sha_path="${xz_path}.sha256"
bin_path="vendor/whisper.cpp/models/ggml-base.en.bin"

if ! compgen -G "${parts_dir}/ggml-base.en.bin.xz.part-*" > /dev/null; then
  echo "Missing model parts in ${parts_dir}" >&2
  exit 1
fi

cat "${parts_dir}"/ggml-base.en.bin.xz.part-* > "${xz_path}"
sha256sum -c "${sha_path}"
xz -d -f -k "${xz_path}"

if [[ ! -f "${bin_path}" ]]; then
  echo "Model reconstruction failed: ${bin_path} was not created" >&2
  exit 1
fi

echo "Rebuilt ${bin_path}"
