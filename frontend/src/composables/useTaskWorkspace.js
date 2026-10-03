import { reactive, ref, watch } from 'vue';
import { readPreference, writePreference } from '../workspacePreferences';

const defaults = () => ({ currentPage:1, pagesize:10, taskid:'', taskname:'', taskgroup:'', status:'', owner:'' });
export function useTaskWorkspace(identity) {
  const tasks = reactive({loading:false,error:'',items:[],total:0,groups:[],params:defaults()});
  const favorites = ref([]), onlyFavorites = ref(false), selectedTasks = ref([]), batchBusy = ref(false);
  const key = () => `wfs:tasks:${identity() || 'anonymous'}`;
  watch(identity, () => {
    const saved = readPreference(key(), {});
    Object.assign(tasks.params, defaults());
    for (const field of Object.keys(tasks.params)) if (['string','number'].includes(typeof saved.filters?.[field])) tasks.params[field] = saved.filters[field];
    tasks.params.currentPage = 1;
    favorites.value = Array.isArray(saved.favorites) ? saved.favorites.filter(id => typeof id === 'string') : [];
    onlyFavorites.value = Boolean(saved.onlyFavorites);
    selectedTasks.value = [];
  }, {immediate:true});
  function saveFilters() { writePreference(key(), {filters:{...tasks.params,currentPage:1},favorites:favorites.value,onlyFavorites:onlyFavorites.value}); }
  function toggleFavorite(id) { favorites.value = favorites.value.includes(id) ? favorites.value.filter(value => value !== id) : [...favorites.value,id]; saveFilters(); }
  function toggleSelected(id) { selectedTasks.value = selectedTasks.value.includes(id) ? selectedTasks.value.filter(value => value !== id) : [...selectedTasks.value,id]; }
  return { tasks, favorites, onlyFavorites, selectedTasks, batchBusy, saveFilters, toggleFavorite, toggleSelected };
}
