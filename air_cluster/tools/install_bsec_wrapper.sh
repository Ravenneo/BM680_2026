#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="${ROOT_DIR}/vendor/bsec"
WRAPPER_DIR="${VENDOR_DIR}/bme68x-python-library-bsec2.6.1.0"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BSEC2_ARCH="${BSEC2_ARCH:-}"

if [[ ! -d "${WRAPPER_DIR}/bsec2-6-1-0_generic_release" ]]; then
  echo "Missing ${WRAPPER_DIR}/bsec2-6-1-0_generic_release"
  echo "Copy or unzip Bosch bsec2-6-1-0_generic_release.zip into ${WRAPPER_DIR}"
  echo "You can inventory the ZIP first with:"
  echo "  python3 tools/prepare_bsec_vendor.py /path/to/bsec2-6-1-0_generic_release.zip --clean"
  exit 2
fi

mkdir -p "${VENDOR_DIR}"
if [[ ! -d "${WRAPPER_DIR}/.git" ]]; then
  git clone https://github.com/mcalisterkm/bme68x-python-library-bsec2.6.1.0.git "${WRAPPER_DIR}"
fi

cd "${WRAPPER_DIR}"
if [[ -z "${BSEC2_ARCH}" ]]; then
  case "$(uname -m)" in
    aarch64|arm64) BSEC2_ARCH=64 ;;
    armv7l|armv8l) BSEC2_ARCH=32 ;;
    *) BSEC2_ARCH="" ;;
  esac
fi

echo "Wrapper checkout: ${WRAPPER_DIR}"
echo "Bosch package: ${WRAPPER_DIR}/bsec2-6-1-0_generic_release"
echo "Python: ${PYTHON_BIN}"
echo "BSEC2: ${BSEC2_ARCH:-default-armv6}"
echo
if [[ -n "${BSEC2_ARCH}" ]]; then
  BSEC2="${BSEC2_ARCH}" "${PYTHON_BIN}" setup.py install
else
  "${PYTHON_BIN}" setup.py install
fi
