from tensorflowglove.tf_glove_copy import GloVeModel
from collections import defaultdict
import os
from random import shuffle
import tensorflow as tf

print('COVER MODEL')

class NotFitToCorpusError(Exception):
    pass

class CoVeRModel(GloVeModel):
    def __init__(self, embedding_size, context_size, max_vocab_size=100000,
                 min_occurrences=5, scaling_factor=3/4, cooccurrence_cap=100, batch_size=512,
                 learning_rate=0.05, num_epochs=50):
        self.embedding_size = embedding_size
        self.context_size = context_size
        self.max_vocab_size = max_vocab_size
        self.min_occurrences = min_occurrences
        self.scaling_factor = scaling_factor
        self.cooccurrence_cap = cooccurrence_cap
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.num_epochs = num_epochs
        self.k = 0
        self.__cooccurrence_tensor = None
        self.__vocab_size = 0

    def iter_corpora(self, corpora): # covariance size?
        print('ITER_CORPORA')
        self.__cooccurrence_tensor = []
        # self.models = []
        for corpus in corpora:
            model = GloVeModel(embedding_size=self.embedding_size,context_size=self.context_size,min_occurrences=self.min_occurrences,learning_rate=self.learning_rate,batch_size=self.batch_size)
            model._GloVeModel__fit_to_corpus(corpus, self.max_vocab_size, self.min_occurrences, model.left_context, model.right_context)
            # self.models.append(model)
            self.__cooccurrence_tensor.append(model._GloVeModel__cooccurrence_matrix)
            self.__vocab_size += self.vocab_size(model)
            self.k += 1


    def update_cooccurrence_tensor(self):
        print('UPDATE TENSOR')
        temp = self.__cooccurrence_tensor
        for i in range(len(temp)):
            dic = self.__cooccurrence_tensor[i]
            t = {}
            for key in dic.keys():
                new_key = key + (i,)
                t[new_key] = dic[key]
            temp[i] = t
        self.__cooccurrence_tensor = {k: v for d in temp for k, v in d.items()}

    def __build_graph(self):#, model):
        print('BUILD GRAPH')
        self.__graph = tf.Graph()
        with self.__graph.as_default(),self.__graph.device(_device_for_node):
            count_max = tf.constant([self.cooccurrence_cap], dtype=tf.float32,
                                     name='max_cooccurrence_count')
            scaling_factor = tf.constant([self.scaling_factor], dtype=tf.float32,
                                         name='scaling_factor')

            self.__focal_input = tf.placeholder(tf.int32, shape=[self.batch_size],
                                                name='focal_words')
            self.__context_input = tf.placeholder(tf.int32, shape=[self.batch_size],
                                                 name='context_words')
            self.__cooccurrence_count = tf.placeholder(tf.float32, shape=[self.batch_size, self.k],
                                                        name='cooccurrence_count')
            ####
            self.__covariance_input = tf.placeholder(tf.int32, shape=[self.batch_size],
                                                     name='covariance')

            focal_embeddings = tf.Variable(
                tf.random_uniform([self.__vocab_size, self.embedding_size], 1.0, -1.0), #voc_size
                name='focal_embeddings')
            context_embeddings = tf.Variable(
                tf.random_uniform([self.__vocab_size, self.embedding_size], 1.0, -1.0),
                name='context_embeddings')
            ####
            covariance_embeddings = tf.Variable(
                tf.random_uniform([self.k, self.embedding_size], 1.0, -1.0),
                name='covariance_embeddings')

            focal_biases = tf.Variable(tf.random_uniform([self.embedding_size, self.k], 1.0, -1.0),
                                       name='focal_biases')
            context_biases = tf.Variable(tf.random_uniform([self.embedding_size, self.k], 1.0, -1.0),
                                         name='context_biases')
            # covariance_biases = tf.Variable(tf.random_uniform([self.k,self.embedding_size], 1.0, -1.0),
            #                                 name='cov_embeddings')

            focal_embedding = tf.nn.embedding_lookup([focal_embeddings], self.__focal_input) # (512,m)

            print('FOCAL EMBEDDINGS', focal_embeddings.shape)
            print('FOCAL EMBEDDING', focal_embedding.shape)

            context_embedding = tf.nn.embedding_lookup([context_embeddings], self.__context_input) # (512,m)
            covariance_embedding = tf.nn.embedding_lookup([covariance_embeddings], self.__covariance_input)

            print('COVARIANCE EMBEDDINGS', covariance_embeddings.shape) 
            print('COVARIANCE EMBEDDING', covariance_embedding.shape)
            
            focal_bias = tf.nn.embedding_lookup([focal_biases], [self.__focal_input, self.__covariance_input])

            print('FOCAL BIASES', focal_biases.shape)
            print('FOCAL BIAS', focal_bias.shape)
            
            context_bias = tf.nn.embedding_lookup([context_biases], [self.__context_input, self.__covariance_input])

            print('CONTEXT BIASES', context_biases.shape)
            print('CONTEXT BIAS', context_bias.shape)

            weighting_factor = tf.minimum(
                1.0,
                tf.pow(
                    tf.div(self.__cooccurrence_count, count_max),
                    scaling_factor))

            foc_cov_product = tf.multiply(focal_embedding, covariance_embedding)
            con_cov_product = tf.multiply(context_embedding, covariance_embedding)
            embedding_product = tf.reduce_sum(tf.multiply(foc_cov_product, con_cov_product),1)
            print('EMBEDDING PRODUCT', embedding_product.shape)

            # foc_cov_bias = tf.transpose(tf.multiply(tf.transpose(covariance_bias), focal_bias))
            # con_cov_bias = tf.transpose(tf.multiply(tf.transpose(covariance_bias), context_bias))

            log_cooccurrences = tf.log(tf.to_float(self.__cooccurrence_count))
            print('LOG COCCURRENCES',log_cooccurrences.shape)

            distance_expr = tf.square(tf.add_n([
                embedding_product,
                focal_bias,
                context_bias,
                tf.negative(log_cooccurrences)])) # ((ck*vi)' * (ck*vj) + bik + bjk - log(Aijk))^2
            print('DISTANCE EXPRESSION', distance_expr.shape)

            single_losses = tf.multiply(weighting_factor, distance_expr)
            print('SINGLE LOSSES', single_losses.shape)
            self.__total_loss = tf.reduce_sum(single_losses)
            print('TOTAL LOSS', self.__total_loss)

    def train(self, self.num_epochs, log_dir=None, summary_batch_interval=1000, tsne_epoch_interval=None):
        should_write_summaries = log_dir is not None and summary_batch_interval
        should_generate_tsne = log_dir is not None and tsne_epoch_interval
        batches = self.__prepare_batches()
        total_steps = 0
        with tf.Session(graph=self.__graph) as session:
            if should_write_summaries:
                print('Writing TensorBoard summaries to {}'.format(log_dir))
                summary_writer = tf.summary.FileWriter(log_dir, graph=session.graph)
            tf.global_cariables_initializer().run
            for epoch in range(num_epochs):
                shuffle(batches)

    def __prepare_batches(self):
        print('PREPARE BATCHES')
        if self.__cooccurrence_tensor is None:
            raise NotFitToCorpusError(
                "Need to fit model to corpus before preparing training batches")
        cooccurrences = [(word_ids[0], word_ids[1], word_ids[2], count) 
                         for word_ids, count in self.__cooccurrence_tensor.items()]
        i_indices, j_indices, k_indices, counts = zip(*cooccurrences)
        return list(_batchify(self.batch_size, i_indices, j_indices, k_indices, counts))

        
    def vocab_size(self, model):
        return len(model._GloVeModel__words)

def _batchify(batch_size, *sequences):
    print('BATCHIFY')
    for i in range(0, len(sequences[0]), batch_size):
        yield tuple(sequence[i:i+batch_size] for sequence in sequences)


def _device_for_node(n):
    if n.type == "Matmul":
        return "/gpu:0"
    else:
        return"/cpu:0"