import { ref } from 'vue';
export const assetFailure = ref(false);
export function isAssetFailure(error) {
  return /failed to fetch dynamically imported module|error loading dynamically imported module|importing a module script failed|loading chunk|unable to preload css/i.test(String(error?.message || error || ''));
}
export function installAssetRecovery(target = window) {
  target.addEventListener('vite:preloadError', () => { assetFailure.value = true; });
}
