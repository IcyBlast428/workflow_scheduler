// Arrange the acyclic part in layers; loop edges return along an outer lane.
export function layoutFlow(graph) {
  if (!graph) return {nodes:[],edges:[],width:720,height:360};
  const nodes = graph.nodes || [];
  const ids = new Set(nodes.map(node => node.id));
  const edges = (graph.edges || []).filter(edge => ids.has(edge.from) && ids.has(edge.to));
  const degrees = new Map(nodes.map(node => [node.id,0]));
  const ranks = new Map(nodes.map(node => [node.id,0]));
  const forward = edges.filter(edge => edge.kind !== 'loop');
  for (const edge of forward) degrees.set(edge.to,degrees.get(edge.to)+1);
  const queue = nodes.filter(node => degrees.get(node.id) === 0).map(node => node.id);
  for (let index=0; index<queue.length; index++) {
    const id=queue[index];
    for (const edge of forward.filter(edge => edge.from === id)) {
      ranks.set(edge.to,Math.max(ranks.get(edge.to),ranks.get(id)+1));
      degrees.set(edge.to,degrees.get(edge.to)-1);
      if (degrees.get(edge.to) === 0) queue.push(edge.to);
    }
  }
  const levels = [];
  for (const node of nodes) (levels[ranks.get(node.id)] ||= []).push(node);
  const widest = Math.max(1,...levels.map(level => level?.length || 0));
  const width = Math.max(700,widest*268+160);
  const positioned = levels.flatMap((level,rank) => (level || []).map((node,index) => ({...node,
    x:width/2+(index-(level.length-1)/2)*268, y:64+rank*132, width:232,height:72})));
  const points = new Map(positioned.map(node=>[node.id,node]));
  const height = Math.max(260,levels.length*132+40);
  const routes = edges.map((edge,index) => {
    const from=points.get(edge.from),to=points.get(edge.to);
    if (edge.kind === 'loop' || to.y <= from.y) {
      const lane=Math.min(width-22,Math.max(from.x,to.x)+164+(index%3)*14);
      return {...edge,path:`M ${from.x+116} ${from.y} C ${lane} ${from.y}, ${lane} ${to.y}, ${to.x+116} ${to.y}`,
        labelX:lane-16,labelY:(from.y+to.y)/2};
    }
    const startY=from.y+36,endY=to.y-36,middle=(startY+endY)/2;
    return {...edge,path:`M ${from.x} ${startY} C ${from.x} ${middle}, ${to.x} ${middle}, ${to.x} ${endY}`,
      labelX:(from.x+to.x)/2+10,labelY:middle-7};
  });
  return {nodes:positioned,edges:routes,width,height};
}

export function flowLabelLines(label) {
  const characters=Array.from(label || '');
  const lines=[];
  for (let index=0;index<characters.length && lines.length<3;index+=20) lines.push(characters.slice(index,index+20).join(''));
  if (characters.length>60) lines[2]=lines[2].slice(0,-1)+'…';
  return lines.length ? lines : ['步骤'];
}
