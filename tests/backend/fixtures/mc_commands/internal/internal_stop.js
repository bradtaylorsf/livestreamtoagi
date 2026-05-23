export const internalStop = {
    name: '!stop',
    description: 'Stop the current bot loop.',
    params: {},
    perform: async function () {
        return 'stopped';
    },
};
