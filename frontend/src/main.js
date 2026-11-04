import { createApp } from 'vue';
import App from './App.vue';
import { installAssetRecovery } from './assetRecovery';
import './styles.css';
import './syntaxHighlight.css';
import './workspace.css';
import { glassSurface } from './glassSurface';

if (!window.__WFS_UNSUPPORTED_BROWSER__) {
  installAssetRecovery();
  createApp(App).directive('glass', glassSurface).mount('#app');
}
