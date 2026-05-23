export const observeAction = {
    name: '!observe',
    description: 'Read nearby pose, blocks, entities, and inventory.',
    params: {
        radius_blocks: {
            type: 'float',
            optional: true,
            description: 'Optional perception radius in blocks.',
        },
        scope: {
            type: 'string',
            optional: true,
            description: 'pose, nearby_blocks, entities, inventory, or all.',
        },
        include_air: {
            type: 'boolean',
            optional: true,
            description: 'Whether nearby block results include air blocks.',
        },
    },
    perform: async function () {
        return 'ok';
    },
};

export default observeAction;
