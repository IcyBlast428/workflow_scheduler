import { createApp } from 'vue';
import App from './App.vue';
import './styles.css';
import { glassSurface } from './glassSurface';

if (!window.__WFS_UNSUPPORTED_BROWSER__) {
  createApp(App).directive('glass', glassSurface).mount('#app');
}
