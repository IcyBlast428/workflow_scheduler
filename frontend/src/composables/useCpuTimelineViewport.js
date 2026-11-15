// Own the view domain and drag listeners so every unmount releases interaction state.
import {ref,watch,onUnmounted} from 'vue';

export function useCpuTimelineViewport({chartRoot,fullRange,plotLeft,plotRight,plotWidth,hasData}) {
  const viewStart = ref(0), viewEnd = ref(0), userNavigated = ref(false);
  const dragging = ref(false), dragLastX = ref(0);
  watch(fullRange, (range, previous) => {
    if (!viewStart.value || !viewEnd.value || !userNavigated.value) {
      viewStart.value = range.start;
      viewEnd.value = range.end;
      return;
    }

    const span = viewEnd.value - viewStart.value;
    const wasAtEnd = previous ? Math.abs(viewEnd.value - previous.end) < 30 * 1000 : false;
    if (wasAtEnd) {
      setDomain(range.end - span, range.end);
    } else {
      setDomain(viewStart.value, viewEnd.value);
    }
  }, { immediate: true });

  function xForTime(time) {
    const span = Math.max(1, viewEnd.value - viewStart.value);
    return plotLeft + ((time - viewStart.value) / span) * plotWidth.value;
  }

  function timeForX(x) {
    const ratio = (Math.max(plotLeft, Math.min(plotRight.value, x)) - plotLeft) / plotWidth.value;
    return viewStart.value + ratio * (viewEnd.value - viewStart.value);
  }

  function setDomain(start, end) {
    const range = fullRange.value;
    const minimumSpan = 60 * 1000;
    const maximumSpan = Math.max(minimumSpan, range.end - range.start);
    let span = Math.max(minimumSpan, Math.min(maximumSpan, end - start));
    let nextStart = start;
    let nextEnd = start + span;

    if (nextStart < range.start) {
      nextStart = range.start;
      nextEnd = nextStart + span;
    }
    if (nextEnd > range.end) {
      nextEnd = range.end;
      nextStart = nextEnd - span;
    }
    if (nextStart < range.start) {
      span = range.end - range.start;
      nextStart = range.start;
      nextEnd = range.start + span;
    }

    viewStart.value = nextStart;
    viewEnd.value = nextEnd;
  }

  function pointX(event) {
    const rect = chartRoot.value.getBoundingClientRect();
    return event.clientX - rect.left;
  }

  function pointY(event) {
    const rect = chartRoot.value.getBoundingClientRect();
    return event.clientY - rect.top;
  }

  function handleWheel(event) {
    if (!hasData.value) {
      return;
    }
    event.preventDefault();
    userNavigated.value = true;
    const x = Math.max(plotLeft, Math.min(plotRight.value, pointX(event)));
    const span = viewEnd.value - viewStart.value;
    const nextSpan = span * (event.deltaY > 0 ? 1.25 : 0.8);
    const rightZoomZoneStart = plotLeft + plotWidth.value * 0.8;
    const center = x >= rightZoomZoneStart ? viewEnd.value : timeForX(x);
    const ratio = x >= rightZoomZoneStart ? 1 : (center - viewStart.value) / span;
    setDomain(center - nextSpan * ratio, center + nextSpan * (1 - ratio));
  }

  function handleMouseDown(event) {
    if (event.button !== 1) {
      return;
    }
    event.preventDefault();
    dragging.value = true;
    userNavigated.value = true;
    dragLastX.value = event.clientX;
    window.addEventListener('mousemove', handleWindowDrag);
    window.addEventListener('mouseup', handleMouseUp);
  }

  function handleWindowDrag(event) {
    if (!dragging.value) {
      return;
    }
    event.preventDefault();
    panByPixels(event.clientX - dragLastX.value);
    dragLastX.value = event.clientX;
  }

  function handleMouseUp() {
    dragging.value = false;
    removeDragListeners();
  }

  function removeDragListeners() {
    window.removeEventListener('mousemove', handleWindowDrag);
    window.removeEventListener('mouseup', handleMouseUp);
  }

  function panByPixels(deltaX) {
    const span = viewEnd.value - viewStart.value;
    const deltaTime = -(deltaX / plotWidth.value) * span;
    setDomain(viewStart.value + deltaTime, viewEnd.value + deltaTime);
  }


  onUnmounted(removeDragListeners);
  return {viewStart,viewEnd,dragging,xForTime,timeForX,pointX,pointY,handleWheel,handleMouseDown};
}
